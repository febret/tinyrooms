"""Nginx world-map generation and installation tests."""

from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from server.mission_control.config import load_mc_config
from server.mission_control.registry import STATUS_RUNNING, STATUS_STOPPED, InstanceRegistry
from server.mission_control.world_map import WorldMapManager, render_world_map
from tests.common import REPO_ROOT
from tests.mc_helpers import mc_env


class WorldMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.target = self.root / "nginx" / "tinyrooms-worlds.map"
        self.target.parent.mkdir(parents=True)
        self.config = load_mc_config(
            env=mc_env(
                self.root,
                TRSERVER_MC_SAME_ORIGIN_WORLDS="1",
                TRSERVER_MC_WORLD_MAP=str(self.target),
                TRSERVER_MC_WORLD_MAP_RELOAD="true",
            ),
            repo_root=REPO_ROOT,
        )
        self.registry = InstanceRegistry()

    def add_instance(self, instance_id: str, port: int, status: str = STATUS_RUNNING) -> None:
        record = self.registry.register_spawned(
            instance_id=instance_id,
            name=instance_id,
            endpoint=f"https://127.0.0.1:{port}",
            instance_dir=str(self.root / instance_id),
            process_handle=None,
            spawn_config={"port": port, "base_path": f"/world/{instance_id}"},
            base_path=f"/world/{instance_id}",
        )
        self.registry.set_status(record.instance_id, status)

    def test_renders_running_instances_and_skips_stopped(self) -> None:
        self.add_instance("mc-one", 10000)
        self.add_instance("mc-two", 10001, STATUS_STOPPED)
        content = render_world_map(self.registry.list())
        self.assertIn('mc-one "https://127.0.0.1:10000";', content)
        self.assertNotIn("mc-two", content)
        self.assertIn('default "";', content)

    def test_update_installs_map_and_reloads(self) -> None:
        self.add_instance("mc-one", 10000)
        calls: list[object] = []

        def runner(command: object, *, shell: bool = False) -> None:
            calls.append((command, shell))
            if isinstance(command, list) and command[:3] == ["sudo", "-n", "install"]:
                shutil.copyfile(command[-2], command[-1])

        manager = WorldMapManager(self.config, self.registry, command_runner=runner)
        manager.update()
        content = self.target.read_text(encoding="utf-8")
        self.assertIn('mc-one "https://127.0.0.1:10000";', content)
        self.assertTrue(any(isinstance(call[0], list) for call in calls))
        self.assertTrue(any(call[1] for call in calls))

    def test_reload_failure_restores_previous_map(self) -> None:
        self.add_instance("mc-one", 10000)
        self.target.write_text(
            'map $tinyrooms_world_id $tinyrooms_world_upstream {\n    default "";\n}\n',
            encoding="utf-8",
        )

        def runner(command: object, *, shell: bool = False) -> None:
            if isinstance(command, list) and command[:3] == ["sudo", "-n", "install"]:
                shutil.copyfile(command[-2], command[-1])
                return
            if shell:
                raise RuntimeError("reload failed")

        manager = WorldMapManager(self.config, self.registry, command_runner=runner)
        with self.assertRaises(RuntimeError):
            manager.update()
        self.assertNotIn("mc-one", self.target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
