"""Cutscene definition loading, launch resolution, and placeholder tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.behaviors.events import BehaviorEvent, PeepRef
from server.behaviors.loader import BehaviorAttachment, BehaviorScripts
from server.commands.core import build_registry
from server.config import KNOWN_FEATURES, load_config
from server.content.common import ContentError
from server.content.cutscenes import (
    load_cutscene_definitions,
    merge_cutscene_definitions,
    parse_param_arguments,
)
from server.services.cards import CardService
from server.security import utc_now
from server.services.cutscenes import CutsceneError, CutsceneService
from server.services.pricing import CardPricingService
from tests.common import REPO_ROOT, ServiceTestCase, WORLD_ID, load_test_world
from tests.test_milestone1 import auth_cookies, websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase
from tests.test_milestone3_behaviors import AsyncServiceTestCase, make_script


CUTSCENE_SCRIPT = "export default async function (ctx) { ctx.stage = true; }\n"


class CutsceneLoaderTests(unittest.TestCase):
    """Strict loader behaviour for a single definition file."""

    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.add_script("demo")
        self.file = self.root / "cutscenes.yaml"

    def add_script(self, cutscene_id: str) -> None:
        """Create a scene directory containing its entry module."""

        directory = self.root / cutscene_id
        directory.mkdir(exist_ok=True)
        (directory / f"{cutscene_id}.js").write_text(CUTSCENE_SCRIPT, encoding="utf-8")

    def write(self, body: str) -> None:
        """Write a cutscenes.yaml body and return the file path."""

        self.file.write_text(body, encoding="utf-8")
        return self.file

    def load(self, body: str, **kwargs):  # type: ignore[no-untyped-def]
        """Load a cutscenes.yaml body with the temp script root."""

        kwargs.setdefault("source", "core")
        kwargs.setdefault("script_roots", (self.root,))
        kwargs.setdefault("known_features", KNOWN_FEATURES)
        return load_cutscene_definitions(self.write(body), **kwargs)

    def test_loads_minimal_definition(self) -> None:
        definitions = self.load("demo:\n  title: Demo\n")
        definition = definitions["demo"]
        self.assertEqual(definition.title, "Demo")
        self.assertEqual(definition.script_name, "demo.js")
        self.assertEqual(definition.frame, "plain")
        self.assertEqual(definition.audience, "private")
        self.assertEqual(definition.duration_ms, 0)
        self.assertTrue(definition.room_bound)
        self.assertTrue(definition.skip)
        self.assertFalse(definition.hidden)
        self.assertEqual(definition.max_queue, 3)
        self.assertIsNotNone(definition.script_path)
        self.assertEqual(definition.script_url, "/cutscenes/demo/demo.js")

    def test_reads_full_definition(self) -> None:
        definitions = self.load(
            "demo:\n"
            "  title: Demo\n"
            "  frame: vs\n"
            "  duration: 4200\n"
            "  audience: room\n"
            "  room_bound: false\n"
            "  skip: false\n"
            "  hidden: true\n"
            "  aliases: [party]\n"
            "  max_queue: 1\n"
            "  feature: world-editor\n"
            "  energy_cost: 2\n"
            "  params: {accent: '#fff', speed: 2, loud: true}\n"
            "  text:\n"
            "    - {at: 350, speaker: Molly, say: 'Purrrr.'}\n"
        )
        definition = definitions["demo"]
        self.assertEqual(definition.frame, "vs")
        self.assertEqual(definition.duration_ms, 4200)
        self.assertEqual(definition.audience, "room")
        self.assertFalse(definition.room_bound)
        self.assertFalse(definition.skip)
        self.assertTrue(definition.hidden)
        self.assertEqual(definition.aliases, ("party",))
        self.assertEqual(definition.max_queue, 1)
        self.assertEqual(definition.required_feature, "world-editor")
        self.assertEqual(definition.energy_cost, 2)
        self.assertEqual(definition.params["speed"], 2)
        self.assertIs(definition.params["loud"], True)
        self.assertEqual(len(definition.text), 1)
        self.assertEqual(definition.text[0].speaker, "Molly")

    def test_rejects_missing_title(self) -> None:
        with self.assertRaises(ContentError):
            self.load("demo:\n  frame: vs\n")

    def test_rejects_missing_script_file(self) -> None:
        with self.assertRaisesRegex(ContentError, "missing script"):
            self.load("demo:\n  title: Demo\n  script: absent.js\n")

    def test_rejects_script_outside_scene_directory(self) -> None:
        with self.assertRaisesRegex(ContentError, "plain file name"):
            self.load("demo:\n  title: Demo\n  script: ../demo.js\n")

    def test_rejects_non_js_script(self) -> None:
        with self.assertRaisesRegex(ContentError, "must be a .js file"):
            self.load("demo:\n  title: Demo\n  script: demo.txt\n")

    def test_rejects_unknown_audience(self) -> None:
        with self.assertRaisesRegex(ContentError, "unknown audience"):
            self.load("demo:\n  title: Demo\n  audience: everyone\n")

    def test_rejects_negative_duration(self) -> None:
        with self.assertRaisesRegex(ContentError, "duration"):
            self.load("demo:\n  title: Demo\n  duration: -1\n")

    def test_rejects_zero_max_queue(self) -> None:
        with self.assertRaisesRegex(ContentError, "max_queue"):
            self.load("demo:\n  title: Demo\n  max_queue: 0\n")

    def test_rejects_non_boolean_hidden(self) -> None:
        with self.assertRaisesRegex(ContentError, "hidden must be a boolean"):
            self.load("demo:\n  title: Demo\n  hidden: sometimes\n")

    def test_rejects_unknown_feature(self) -> None:
        with self.assertRaisesRegex(ContentError, "unknown feature"):
            self.load("demo:\n  title: Demo\n  feature: nope\n")

    def test_rejects_unknown_power(self) -> None:
        with self.assertRaisesRegex(ContentError, "unknown power"):
            self.load(
                "demo:\n  title: Demo\n  power: wizard\n",
                known_powers=frozenset({"admin"}),
            )

    def test_rejects_unknown_room(self) -> None:
        with self.assertRaisesRegex(ContentError, "unknown room"):
            self.load(
                "demo:\n  title: Demo\n  rooms: [nowhere]\n",
                known_rooms=frozenset({"hub"}),
            )

    def test_rejects_non_scalar_params(self) -> None:
        with self.assertRaisesRegex(ContentError, "must be a string, number, or"):
            self.load("demo:\n  title: Demo\n  params: {nope: [1, 2]}\n")

    def test_allows_frame_options_mapping(self) -> None:
        definitions = self.load(
            "demo:\n  title: Demo\n  params: {frame_options: {from: left, duration: 500}}\n"
        )
        self.assertEqual(definitions["demo"].params["frame_options"]["from"], "left")

    def test_rejects_non_mapping_frame_options(self) -> None:
        with self.assertRaisesRegex(ContentError, "frame_options"):
            self.load("demo:\n  title: Demo\n  params: {frame_options: left}\n")

    def test_rejects_cue_without_text(self) -> None:
        with self.assertRaisesRegex(ContentError, "needs say or speaker"):
            self.load("demo:\n  title: Demo\n  text:\n    - {at: 100}\n")

    def test_rejects_repeated_alias(self) -> None:
        with self.assertRaisesRegex(ContentError, "repeats an alias"):
            self.load("demo:\n  title: Demo\n  aliases: [a, a]\n")

    def test_missing_file_is_empty(self) -> None:
        self.assertEqual(load_cutscene_definitions(self.root / "absent.yaml", source="core"), {})

    def test_merge_rejects_duplicate_ids(self) -> None:
        first = self.load("demo:\n  title: One\n")
        second = load_cutscene_definitions(
            self.write("demo:\n  title: Two\n"), source="world", script_roots=(self.root,)
        )
        with self.assertRaisesRegex(ContentError, "Duplicate cutscene id"):
            merge_cutscene_definitions(first, second)

    def test_merge_rejects_alias_collisions(self) -> None:
        self.add_script("one")
        self.add_script("two")
        first = self.load("one:\n  title: One\n  aliases: [shared]\n")
        second = load_cutscene_definitions(
            self.write("two:\n  title: Two\n  aliases: [shared]\n"),
            source="world",
            script_roots=(self.root,),
        )
        with self.assertRaisesRegex(ContentError, "claimed by both"):
            merge_cutscene_definitions(first, second)


class ParamArgumentTests(unittest.TestCase):
    """Launch argument parsing."""

    def test_parses_scalars(self) -> None:
        params = parse_param_arguments(["accent=#fff", "speed=2", "loud=true", "note=hello world"])
        self.assertEqual(params, {"accent": "#fff", "speed": 2, "loud": True, "note": "hello world"})

    def test_rejects_reserved_keys(self) -> None:
        with self.assertRaisesRegex(ContentError, "reserved"):
            parse_param_arguments(["room_id=hub"])

    def test_rejects_pairs_without_equals(self) -> None:
        with self.assertRaisesRegex(ContentError, "key=value"):
            parse_param_arguments(["accent"])


class CutsceneCatalogTests(unittest.TestCase):
    """The checked-in core and tutorial catalogs."""

    def test_core_catalog_loads(self) -> None:
        definitions = load_cutscene_definitions(
            REPO_ROOT / "data" / "core" / "cutscenes.yaml",
            source="core",
            script_roots=(REPO_ROOT / "data" / "cutscenes",),
            known_features=KNOWN_FEATURES,
        )
        self.assertIn("victory-dance", definitions)
        definition = definitions["victory-dance"]
        self.assertEqual(definition.audience, "room")
        self.assertEqual(definition.frame, "vs")
        self.assertFalse(definition.room_bound)
        self.assertIsNotNone(definition.script_path)

    def test_tutorial_world_catalog_loads(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / WORLD_ID)
        self.assertIn("molly-greet", world.cutscenes)
        self.assertIn("victory-dance", world.cutscenes)
        self.assertEqual(world.cutscenes["molly-greet"].aliases, ("greet",))


class CutsceneServiceTestCase(ServiceTestCase):
    """Provide a cutscene service over an isolated database."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / WORLD_ID)
        self.config = self._config_with()
        self.pricing = CardPricingService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.cards = CardService(self.hub, self.profiles, None, self.catalog, WORLD_ID, None, self.pricing)
        self.cutscenes = CutsceneService(
            self.config,
            world=lambda: self.world,
            profiles=self.profiles,
            cards=self.cards,
            valid_stickers=frozenset({"s1", "s2"}),
        )

    def _config_with(self, *features: str):
        base = load_config(
            env={
                "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                "TRSERVER_USERS_PATH": str(Path(self.temporary_directory.name) / "users"),
                "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / WORLD_ID),
                "TRSERVER_WORLDSTATE_PATH": str(
                    Path(self.temporary_directory.name) / "worldstate.sqlite3"
                ),
                "TRSERVER_FEATURES": ",".join(features),
                "TRSERVER_TIMEZONE": "UTC",
            },
            repo_root=REPO_ROOT,
        )
        return replace(base, features=frozenset(features))


class CutsceneResolutionTests(CutsceneServiceTestCase):
    """Definition resolution and audience decisions."""

    def test_resolves_by_id_and_alias(self) -> None:
        self.assertEqual(self.cutscenes.resolve("molly-greet").id, "molly-greet")
        self.assertEqual(self.cutscenes.resolve("greet").id, "molly-greet")

    def test_unknown_reference_raises(self) -> None:
        with self.assertRaisesRegex(CutsceneError, "no cutscene called"):
            self.cutscenes.resolve("nope")

    def test_cutscenes_need_no_feature_flag(self) -> None:
        self.assertIn("molly-greet", self.cutscenes.definitions())
        self.assertEqual(self.config.features, frozenset())

    def test_audience_defaults_to_definition(self) -> None:
        self.assertEqual(
            self.cutscenes.choose_audience(self.cutscenes.resolve("molly-greet")), "private"
        )
        self.assertEqual(
            self.cutscenes.choose_audience(self.cutscenes.resolve("victory-dance")), "room"
        )

    def test_promotion_requires_permission(self) -> None:
        private = self.cutscenes.resolve("molly-greet")
        with self.assertRaisesRegex(CutsceneError, "whole room"):
            self.cutscenes.choose_audience(private, "room")
        self.assertEqual(self.cutscenes.choose_audience(private, "private"), "private")
        self.assertEqual(self.cutscenes.choose_audience(private, None), "private")

    def test_check_allows_unguarded_definition(self) -> None:
        self.cutscenes.check(
            self.cutscenes.resolve("molly-greet"), room_id="hub", has_power=lambda name: True
        )

    def test_check_rejects_other_room(self) -> None:
        definition = replace(self.cutscenes.resolve("molly-greet"), rooms=("playroom",))
        with self.assertRaisesRegex(CutsceneError, "not available here"):
            self.cutscenes.check(definition, room_id="hub", has_power=lambda name: True)

    def test_check_rejects_missing_power(self) -> None:
        definition = replace(self.cutscenes.resolve("molly-greet"), power="admin")
        with self.assertRaisesRegex(CutsceneError, "not available"):
            self.cutscenes.check(definition, room_id="hub", has_power=lambda name: False)

    def test_item_card_may_reference_a_room_cutscene(self) -> None:
        definition = self.catalog.cards["vacuum-cleaner"]
        self.assertEqual(definition.type, "item")
        self.assertEqual(definition.cutscene, "centipede-vacuum")
        self.assertEqual(self.cutscenes.resolve(definition.cutscene).audience, "room")

    def test_check_rejects_missing_feature(self) -> None:
        definition = replace(self.cutscenes.resolve("molly-greet"), required_feature="world-editor")
        service = CutsceneService(
            self._config_with(),
            world=lambda: self.world,
            profiles=self.profiles,
            cards=self.cards,
            valid_stickers=frozenset(),
        )
        with self.assertRaisesRegex(CutsceneError, "not available"):
            service.check(definition, room_id="hub", has_power=lambda name: True)

    def test_visible_catalog_filters_rooms(self) -> None:
        entries = self.cutscenes.visible_catalog(room_id="hub")
        self.assertEqual(
            {entry["id"] for entry in entries},
            {"molly-greet", "tutorial-end", "centipede-vacuum", "victory-dance", "pack-open"},
        )
        for entry in entries:
            self.assertNotIn("script_url", entry)

    def test_visible_catalog_hides_hidden_cutscenes(self) -> None:
        entries = self.cutscenes.visible_catalog(room_id="hub")
        self.assertNotIn("task-started", {entry["id"] for entry in entries})
        self.assertNotIn("task-completed", {entry["id"] for entry in entries})
        self.assertTrue(self.cutscenes.resolve("task-started").hidden)
        self.assertTrue(self.cutscenes.resolve("task-completed").hidden)


class CutsceneLaunchTests(CutsceneServiceTestCase):
    """Play payload construction and placeholder resolution."""

    def setUp(self) -> None:
        super().setUp()
        self.account = self.create_account("molly-fan", room="playroom")
        self.room_id = "playroom"
        self.occupants = [self.account.id]

    def launch(self, cutscene_id: str, **kwargs):  # type: ignore[no-untyped-def]
        """Launch a cutscene for the test account."""

        kwargs.setdefault("occupants", self.occupants)
        return self.cutscenes.launch(
            definition=self.cutscenes.resolve(cutscene_id),
            account=self.account,
            room_id=self.room_id,
            audience=kwargs.pop("audience", "private"),
            origin=kwargs.pop("origin", "command"),
            **kwargs,
        )

    def test_event_shape(self) -> None:
        launch = self.launch("molly-greet")
        self.assertEqual(launch.event["type"], "cutscene.play")
        self.assertEqual(launch.event["room_id"], "playroom")
        self.assertEqual(launch.event["account_id"], self.account.id)
        payload = launch.event["cutscene"]
        self.assertEqual(payload["id"], "molly-greet")
        self.assertEqual(payload["script_url"], "/cutscenes/molly-greet/molly-greet.js")
        self.assertEqual(payload["frame"], "movie")
        self.assertEqual(payload["origin"], "command")
        self.assertEqual(payload["source"], {"id": self.account.id, "name": self.account.username_display})

    def test_script_url_honors_base_path(self) -> None:
        service = CutsceneService(
            replace(self.config, base_path="/admin"),
            world=lambda: self.world,
            profiles=self.profiles,
            cards=self.cards,
            valid_stickers=frozenset({"s1", "s2"}),
        )
        account = self.create_account("based", room="playroom")
        launch = service.launch(
            definition=service.resolve("molly-greet"),
            account=account,
            room_id="playroom",
            audience="private",
            origin="command",
            occupants=[account.id],
        )
        self.assertEqual(
            launch.event["cutscene"]["script_url"],
            "/admin/cutscenes/molly-greet/molly-greet.js",
        )

    def test_room_wide_event_has_no_account_id(self) -> None:
        launch = self.launch("victory-dance", audience="room")
        self.assertNotIn("account_id", launch.event)
        self.assertTrue(launch.is_room_wide)

    def test_reserved_params_are_injected(self) -> None:
        params = self.launch("molly-greet").params
        self.assertEqual(params["origin"], "command")
        self.assertEqual(params["source_name"], self.account.username_display)
        self.assertEqual(params["room_id"], "playroom")
        self.assertIsInstance(params["random"], int)

    def test_launch_params_override_definition(self) -> None:
        launch = self.launch("molly-greet", params={"stage_background": "#ffffff"})
        self.assertEqual(launch.params["stage_background"], "#ffffff")

    def test_me_placeholder_resolves(self) -> None:
        account = self.profiles.set_sticker(self.account.id, "s1")
        launch = self.cutscenes.launch(
            definition=self.cutscenes.resolve("molly-greet"),
            account=account,
            room_id=self.room_id,
            audience="private",
            origin="peep",
            params={"sprite": "$me"},
            occupants=self.occupants,
        )
        self.assertEqual(len(launch.assets), 1)
        asset = launch.assets[0]
        self.assertEqual(asset["ref"], "$me")
        self.assertEqual(asset["kind"], "sticker")
        self.assertEqual(asset["url"], "/assets/stickers/s1")

    def test_peep_placeholder_resolves(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$peep:molly"})
        self.assertEqual(launch.assets[0]["kind"], "sticker")
        self.assertEqual(launch.assets[0]["id"], "molly")
        self.assertIn("/peeps/molly.png", str(launch.assets[0]["url"]))

    def test_prop_placeholder_resolves(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$prop:dollhouse0"})
        asset = launch.assets[0]
        self.assertEqual(asset["kind"], "prop")
        self.assertEqual(asset["id"], "dollhouse0")
        self.assertIsNone(asset["thumbnail"])
        self.assertGreater(float(asset["scale"]), 0)

    def test_sticker_placeholder_resolves(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$sticker:s2"})
        self.assertEqual(launch.assets[0]["url"], "/assets/stickers/s2")

    def test_card_placeholder_resolves(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$card:smile"})
        asset = launch.assets[0]
        self.assertEqual(asset["kind"], "card")
        self.assertEqual(asset["id"], "smile")
        self.assertEqual(asset["url"], "/assets/base/smile.webp")

    def test_card_placeholder_by_stack_id(self) -> None:
        stack_id = self.grant_card(self.account, "smile")
        launch = self.launch("molly-greet", params={"sprite": f"$card:{stack_id}"})
        self.assertEqual(launch.assets[0]["id"], "smile")

    def test_unowned_card_placeholder_is_skipped(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$card:not-a-stack"})
        self.assertEqual(launch.assets, ())

    def test_cross_room_prop_placeholder_is_skipped(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$prop:archway0"})
        self.assertEqual(launch.assets, ())

    def test_user_placeholder_requires_occupancy(self) -> None:
        other = self.profiles.set_sticker(self.create_account("neighbour").id, "s2")
        launch = self.launch("molly-greet", params={"sprite": f"$user:{other.id}"})
        self.assertEqual(launch.assets, ())
        allowed = self.launch(
            "molly-greet", params={"sprite": f"$user:{other.id}"}, occupants=[other.id]
        )
        self.assertEqual(len(allowed.assets), 1)
        self.assertEqual(allowed.assets[0]["url"], "/assets/stickers/s2")

    def test_unknown_placeholder_is_skipped(self) -> None:
        launch = self.launch("molly-greet", params={"sprite": "$nonsense:thing"})
        self.assertEqual(launch.assets, ())

    def test_caption_tokens_become_labels(self) -> None:
        account = self.profiles.set_sticker(self.account.id, "s1")
        launch = self.cutscenes.launch(
            definition=self.cutscenes.resolve("molly-greet"),
            account=account,
            room_id=self.room_id,
            audience="private",
            origin="peep",
            params={"caption": "$me"},
            occupants=self.occupants,
        )
        cues = launch.event["cutscene"]["text"]
        self.assertEqual(cues[0]["say"], "Purrrr.")
        self.assertEqual(
            cues[1]["say"],
            f"{self.account.username_display}, you again? Good.",
        )


class CutsceneCommandTests(Milestone2IntegrationTestCase):
    """End-to-end command, trigger, and protocol coverage for cutscenes."""

    features = "world-editor,card-database,prop-editor"

    def cutscene_events(self, result: dict[str, object]) -> list[dict[str, object]]:
        """Return every cutscene play event in a command result."""

        return [event for event in result["events"] if event["type"] == "cutscene.play"]

    def open_socket(self, credentials: dict[str, str]):
        """Open a command socket for an account."""

        return self.client.websocket_connect(
            "/ws", headers=websocket_headers(**credentials)
        )

    def exchange(self, socket, text: str, request_id: str = "cutscene-test") -> dict[str, object]:
        """Send a command and wait past the opening snapshot for its result."""

        socket.send_json(
            {"v": 1, "type": "command", "request_id": request_id, "command": text}
        )
        for _ in range(12):
            message = socket.receive_json()
            if message.get("type") == "result" and message.get("request_id") == request_id:
                return message
        raise AssertionError(f"Never received a result for {text!r}.")

    def send(self, text: str, username: str = "plum") -> dict[str, object]:
        """Run one command for a throwaway ready account and return the result."""

        credentials = self.create_ready_account(username)
        with self.open_socket(credentials) as socket:
            return self.exchange(socket, text)

    def test_command_plays_a_private_cutscene(self) -> None:
        result = self.send(".cutscene molly-greet")
        self.assertTrue(result["ok"], result)
        events = self.cutscene_events(result)
        self.assertEqual(len(events), 1)
        cutscene = events[0]["cutscene"]
        self.assertEqual(cutscene["id"], "molly-greet")
        self.assertEqual(cutscene["audience"], "private")
        self.assertEqual(cutscene["origin"], "command")
        self.assertEqual(cutscene["script_url"], "/cutscenes/molly-greet/molly-greet.js")
        self.assertTrue(cutscene["room_bound"])
        self.assertIs(result["toast"], False, "a cutscene is its own feedback")

    def test_command_accepts_an_alias(self) -> None:
        result = self.send(".cutscene greet")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.cutscene_events(result)), 1)

    def test_command_rejects_an_unknown_cutscene(self) -> None:
        result = self.send(".cutscene nope")
        self.assertFalse(result["ok"])
        self.assertIn("no cutscene called", result["message"])

    def test_command_requires_a_reference(self) -> None:
        self.assertFalse(self.send(".cutscene")["ok"])

    def test_command_passes_key_value_params(self) -> None:
        result = self.send(".cutscene molly-greet stage_background=#ffffff")
        self.assertTrue(result["ok"], result)
        params = self.cutscene_events(result)[0]["cutscene"]["params"]
        self.assertEqual(params["stage_background"], "#ffffff")
        self.assertEqual(params["origin"], "command")
        self.assertEqual(params["room_id"], "hub")

    def test_command_rejects_reserved_params(self) -> None:
        result = self.send(".cutscene molly-greet room_id=hub")
        self.assertFalse(result["ok"])
        self.assertIn("reserved", result["message"])

    def test_command_injects_a_prop_placeholder(self) -> None:
        result = self.send(".cutscene molly-greet @prop:portal0")
        self.assertTrue(result["ok"], result)
        cutscene = self.cutscene_events(result)[0]["cutscene"]
        self.assertEqual(cutscene["origin"], "prop")
        self.assertEqual(cutscene["params"]["prop"], "$prop:portal0")
        self.assertIn("$prop:portal0", {asset["ref"] for asset in cutscene["assets"]})

    def test_room_audience_requires_permission(self) -> None:
        result = self.send(".cutscene molly-greet --room")
        self.assertFalse(result["ok"])
        self.assertIn("whole room", result["message"])

    def test_room_definition_uses_a_broadcast(self) -> None:
        credentials = self.create_ready_account("plum")
        with self.open_socket(credentials) as socket:
            result = self.exchange(socket, ".cutscene victory-dance")
            self.assertTrue(result["ok"], result)
            self.assertEqual(self.cutscene_events(result), [])
            event = self.drain_until(socket, "cutscene.play")
            self.assertEqual(event["cutscene"]["audience"], "room")
            self.assertEqual(event["cutscene"]["origin"], "command")

    def test_authored_cutscene_action_serializes(self) -> None:
        peep = self.runtime().world.peeps["molly"]
        self.assertFalse(hasattr(peep, "cutscene"))
        actions = self.runtime().rooms.serialize_npc(peep)["quick_actions"]
        self.assertIn(".cutscene molly-greet @peep:molly", [entry["command"] for entry in actions])
        self.assertIn("Greet", [entry["label"] for entry in actions])

    def test_cutscene_emote_broadcasts_instead_of_a_bubble(self) -> None:
        credentials = self.create_ready_account("plum")
        stack_id = self.grant_card(self.account_id(credentials), "victory-dance")
        with self.open_socket(credentials) as socket:
            result = self.exchange(socket, f".emote @card:{stack_id}")
            self.assertTrue(result["ok"], result)
            self.assertIn("used Victory Dance", result["message"])
            event = self.drain_until(socket, "cutscene.play")
            self.assertEqual(event["cutscene"]["id"], "victory-dance")
            self.assertEqual(event["cutscene"]["origin"], "emote")
            self.assertEqual(event["cutscene"]["params"]["card"], "victory-dance")
            self.assertFalse(event["cutscene"]["room_bound"])

    def test_cutscene_emote_charges_energy(self) -> None:
        credentials = self.create_ready_account("plum")
        account_id = self.account_id(credentials)
        runtime = self.runtime()
        with runtime.hub.transaction() as connection:
            runtime.stats.charge_in_transaction(connection, account_id, 30)
        before = runtime.profiles.get_account_by_id(account_id).shared_energy
        stack_id = self.grant_card(account_id, "victory-dance")
        with self.open_socket(credentials) as socket:
            self.assertTrue(self.exchange(socket, f".emote @card:{stack_id}")["ok"])
        after = self.runtime().profiles.get_account_by_id(account_id).shared_energy
        self.assertLess(after, before)

    def test_catalog_route_lists_visible_cutscenes(self) -> None:
        credentials = self.create_ready_account("plum")
        response = self.client.get("/api/cutscenes", cookies=auth_cookies(**credentials))
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["cutscenes"]
        self.assertEqual(
            {entry["id"] for entry in entries},
            {"molly-greet", "tutorial-end", "centipede-vacuum", "victory-dance", "pack-open"},
        )
        for entry in entries:
            self.assertNotIn("script_url", entry)

    def test_catalog_route_requires_a_session(self) -> None:
        self.assertEqual(self.client.get("/api/cutscenes").status_code, 401)

    def test_script_route_serves_the_module(self) -> None:
        response = self.client.get("/cutscenes/molly-greet/molly-greet.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("beginCutscene", response.text)
        self.assertIn("javascript", response.headers.get("content-type", ""))

    def test_script_route_404s_an_unknown_cutscene(self) -> None:
        self.assertEqual(self.client.get("/cutscenes/nope/nope.js").status_code, 404)

    def test_command_is_always_registered(self) -> None:
        self.assertIn("cutscene", {spec.name for spec in build_registry().list()})


class CutsceneBehaviorIntentTests(AsyncServiceTestCase):
    """The behavior ``cutscene`` intent reaches the right audience."""

    def build_with(self, handler, *, features: frozenset[str] = frozenset()):  # type: ignore[no-untyped-def]
        """Build a dispatcher whose room script requests a cutscene."""

        script = make_script({"on_tick": handler})
        ref = PeepRef(kind="npc", peep_id="molly", account_id=None)
        scripts = BehaviorScripts(
            scripts={"fake": script},
            peep_attachments={"molly": BehaviorAttachment("fake", "peep", "molly", ref)},
            prop_attachments={},
            room_attachments={"playroom": (BehaviorAttachment("fake", "prop", "molly", ref),)},
        )
        runtime = self.build(scripts)
        runtime.dispatcher._cutscenes = self.cutscene_service(features)
        return runtime

    def cutscene_service(self, features: frozenset[str]):  # type: ignore[no-untyped-def]
        """Return a cutscene service over the tutorial catalog."""

        from server.config import load_config
        from server.services.cards import CardService
        from server.services.cutscenes import CutsceneService
        from server.services.pricing import CardPricingService

        config = replace(
            load_config(
                env={
                    "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                    "TRSERVER_USERS_PATH": str(Path(self.temporary_directory.name) / "users"),
                    "TRSERVER_WORLDSTATE_PATH": str(
                        Path(self.temporary_directory.name) / "worldstate.sqlite3"
                    ),
                    "TRSERVER_FEATURES": ",".join(sorted(features)),
                },
                repo_root=REPO_ROOT,
            ),
            features=features,
        )
        pricing = CardPricingService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        cards = CardService(self.hub, self.profiles, None, self.catalog, WORLD_ID, None, pricing)
        return CutsceneService(
            config,
            world=lambda: self.world,
            profiles=self.profiles,
            cards=cards,
            valid_stickers=frozenset({"s1"}),
        )

    async def test_intent_plays_a_private_cutscene(self) -> None:
        account = self.create_account("plum")
        runtime = self.build_with(lambda context, event: context.cutscene("molly-greet"))
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        result = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="tick", actor=actor, room_id="playroom")
        )
        plays = [item for item in result.private_events if item["type"] == "cutscene.play"]
        self.assertEqual(len(plays), 1)
        self.assertEqual(result.room_broadcasts, [])
        self.assertEqual(plays[0]["account_id"], account.id)
        self.assertEqual(plays[0]["cutscene"]["origin"], "behavior")

    async def test_intent_can_broadcast_to_the_room(self) -> None:
        account = self.create_account("plum")
        runtime = self.build_with(
            lambda context, event: context.cutscene("victory-dance", audience="room")
        )
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        result = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="tick", actor=actor, room_id="playroom")
        )
        self.assertEqual(result.private_events, [])
        self.assertEqual(len(result.room_broadcasts), 1)
        self.assertEqual(result.room_broadcasts[0].event["cutscene"]["audience"], "room")

    async def test_unknown_cutscene_is_skipped_not_raised(self) -> None:
        account = self.create_account("plum")
        runtime = self.build_with(lambda context, event: context.cutscene("nope"))
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        result = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="tick", actor=actor, room_id="playroom")
        )
        self.assertEqual(result.private_events, [])
        self.assertEqual(result.room_broadcasts, [])

    async def test_intent_needs_no_feature_flag(self) -> None:
        account = self.create_account("plum")
        runtime = self.build_with(lambda context, event: context.cutscene("molly-greet"))
        actor = PeepRef(kind="user", peep_id=None, account_id=account.id)
        result = await runtime.dispatcher.dispatch(
            BehaviorEvent(type="tick", actor=actor, room_id="playroom")
        )
        plays = [item for item in result.private_events if item["type"] == "cutscene.play"]
        self.assertEqual(len(plays), 1)


if __name__ == "__main__":
    unittest.main()
