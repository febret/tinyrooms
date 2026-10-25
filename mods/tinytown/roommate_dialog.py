"""Runtime-generated roommate dialog trees: status, house, interests, work, chat."""

from __future__ import annotations

from mods.tinytown.interests import interest_blurb, interest_label
from server.content.worlds import DialogChoice, DialogDefinition, DialogNode


def condition_label(value: float) -> str:
    """Describe one condition meter without numbers."""

    score = float(value)
    if score >= 80:
        return "glowing"
    if score >= 60:
        return "steady"
    if score >= 40:
        return "a little worn"
    if score >= 20:
        return "running on fumes"
    return "ready to drop"


def build_roommate_dialog(
    record,
    *,
    owner_toward_label: str,
    owner_from_label: str,
    housemates: list[dict[str, str]],
    needs_blurb: str,
    job_label_text: str,
    job_description_text: str,
    job_state: str,
    job_gate_blurb: str,
    job_ready: dict[str, object] | None,
    energy_label: str,
    health_label: str,
    cleanliness_label: str,
) -> object:
    """Build a ~20-node, 2–3 layer dialog tree for one roommate."""

    likes_label = interest_label(getattr(record, "likes", ""))
    dislikes_label = interest_label(getattr(record, "dislikes", ""))
    likes_blurb = interest_blurb(getattr(record, "likes", ""))
    dislikes_blurb = interest_blurb(getattr(record, "dislikes", ""))
    name = record.name
    action_label = str(getattr(record, "action", "idle"))
    target = str(getattr(record, "target", ""))

    nodes: dict[str, DialogNode] = {}

    def add(node_id: str, text: str, choices: list[DialogChoice]) -> None:
        nodes[node_id] = DialogNode(id=node_id, text=text, choices=tuple(choices))

    def choice(
        index: int,
        label: str,
        *,
        next_node: str | None = None,
        end: bool = False,
        vibe_delta: int = 0,
        give_card: str | None = None,
        grant_bops: int = 0,
        action: str | None = None,
        repeatable: bool = False,
    ) -> DialogChoice:
        return DialogChoice(
            index=index,
            label=label,
            action_id=f"{_current_node[0]}:{index}",
            next_node_id=next_node,
            end=end,
            when=None,
            script=None,
            action=action,
            give_card=give_card,
            start_task=None,
            grant=0,
            vibe_delta=vibe_delta,
            grant_bops=grant_bops,
            repeatable=repeatable,
        )

    _current_node = ["start"]

    def choices_for(node_id: str, specs: list[dict]) -> list[DialogChoice]:
        _current_node[0] = node_id
        built: list[DialogChoice] = []
        for index, spec in enumerate(specs):
            built.append(choice(index, spec["label"], **{k: v for k, v in spec.items() if k != "label"}))
        return built

    doing = f" {target}" if target and action_label not in {"idle"} else ""
    add(
        "start",
        f"“Hey! Got a minute?” {name} looks up, {action_label}{doing}. “What's on your mind?”",
        choices_for(
            "start",
            [
                {"label": "How are you doing?", "next_node": "status"},
                {"label": "How is the house feeling?", "next_node": "house"},
                {"label": "What are you into lately?", "next_node": "interests"},
                {"label": "How is the work going?", "next_node": "work"},
                {"label": "Just chatting.", "next_node": "chat"},
                {"label": "Lovely — see you round!", "end": True, "repeatable": True},
            ],
        ),
    )

    add(
        "status",
        f"“Honestly? My energy feels {energy_label}, my health {health_label}, and, well, cleanliness-wise I'm {cleanliness_label}. But I'm upright!”",
        choices_for(
            "status",
            [
                {"label": "Tell me more.", "next_node": "status_body"},
                {"label": "What are you up to right now?", "next_node": "status_mood"},
                {"label": "Ask about something else.", "next_node": "start"},
            ],
        ),
    )
    add(
        "status_body",
        "“Sleep sorts the energy, good food sorts the health, and a long bath sorts everything else. You know how it is. How are YOU holding up?”",
        choices_for(
            "status_body",
            [
                {"label": "“Hanging in there!”", "next_node": "status_mood", "vibe_delta": 1, "repeatable": True},
                {"label": "Back to the start.", "next_node": "start"},
            ],
        ),
    )
    add(
        "status_mood",
        f"“Right now I'm {action_label}{doing}. The light in here is doing half the work, I swear.”",
        choices_for(
            "status_mood",
            [
                {"label": "“Sounds lovely.”", "next_node": "start", "vibe_delta": 1, "repeatable": True},
                {"label": "Ask about the house.", "next_node": "house"},
            ],
        ),
    )

    house_mate_choices = []
    for position, mate in enumerate(housemates[:3]):
        house_mate_choices.append({"label": f"How are you and {mate['name']}?", "next_node": f"house_mate_{position}"})
    add(
        "house",
        f"“The house? {needs_blurb} What do you want to know?”",
        choices_for(
            "house",
            [
                *house_mate_choices,
                {"label": "How are you and I doing?", "next_node": "house_owner"},
                {"label": "Ask about something else.", "next_node": "start"},
            ],
        ),
    )
    for position, mate in enumerate(housemates[:3]):
        add(
            f"house_mate_{position}",
            f"“{mate['name']}? Toward them I feel {mate['toward_label']}, and I'd say they feel {mate['from_label']} about me. It's {mate['reason']}, mostly.”",
            choices_for(
                f"house_mate_{position}",
                [
                    {"label": "“I'm glad.”", "next_node": "house", "vibe_delta": 1, "repeatable": True},
                    {"label": "Back to house talk.", "next_node": "house"},
                ],
            ),
        )
    add(
        "house_owner",
        f"“You and me? I feel {owner_from_label} toward you — and I'd guess you feel {owner_toward_label} toward me. Sharing a hallway counts for a lot, you know.”",
        choices_for(
            "house_owner",
            [
                {"label": "“Right back at you.”", "next_node": "house", "vibe_delta": 2, "repeatable": True},
                {"label": "“We need to talk…”", "next_node": "house", "vibe_delta": -2, "repeatable": True},
            ],
        ),
    )

    add(
        "interests",
        f"“Lately? {likes_blurb} On the other hand — {dislikes_blurb}” {name} shrugs. “Everyone's got a thing.”",
        choices_for(
            "interests",
            [
                {"label": f"Why do you love {likes_label}?", "next_node": "interests_likes"},
                {"label": f"What's wrong with {dislikes_label}?", "next_node": "interests_dislikes"},
                {"label": "Do we have anything in common?", "next_node": "interests_you"},
                {"label": "Ask about something else.", "next_node": "start"},
            ],
        ),
    )
    add(
        "interests_likes",
        f"“{likes_label.capitalize()}? Where do I start. It is the highlight of my week, every week.” {name}'s eyes light up.",
        choices_for(
            "interests_likes",
            [
                {"label": f"“I love {likes_label} too!”", "next_node": "interests", "vibe_delta": 2, "repeatable": True},
                {"label": f"“I never got {likes_label}…”", "next_node": "interests", "vibe_delta": -1, "repeatable": True},
            ],
        ),
    )
    add(
        "interests_dislikes",
        f"“{dislikes_label.capitalize()}? No offence to anyone, but life is short.” {name} wrinkles their nose dramatically.",
        choices_for(
            "interests_dislikes",
            [
                {"label": f"“Honestly, same.”", "next_node": "interests", "vibe_delta": 2, "repeatable": True},
                {"label": f"“Hey, {dislikes_label} is great!”", "next_node": "interests", "vibe_delta": -1, "repeatable": True},
            ],
        ),
    )
    add(
        "interests_you",
        "“Let's see… you strike me as someone with strong snack opinions and a soft spot for a good hallway chat. Close?”",
        choices_for(
            "interests_you",
            [
                {"label": "“Spot on!”", "next_node": "start", "vibe_delta": 2, "repeatable": True},
                {"label": "“You have no idea.”", "next_node": "start", "vibe_delta": -1, "repeatable": True},
            ],
        ),
    )

    bucket = ""
    if job_state == "ready" and isinstance(job_ready, dict):
        bucket = str(job_ready.get("bucket") or "")
    claim_node_id = f"work_claim_{bucket}" if bucket else "work_claim"
    work_claim_specs: list[dict] = []
    if job_state == "ready" and isinstance(job_ready, dict) and bucket:
        cards = [str(card) for card in (job_ready.get("cards") or []) if str(card)]
        bops = int(job_ready.get("bops") or 0)
        npc_id = str(getattr(record, "npc_id", ""))
        if cards:
            for position, card_id in enumerate(cards):
                work_claim_specs.append(
                    {
                        "label": "“What did you make? Can I have it?”"
                        if position == 0
                        else "“Ooh — and the other one?”",
                        "next_node": None,
                        "end": True,
                        "give_card": card_id,
                        "action": f"tinytown_claim:{npc_id}:{bucket}:{position}",
                    }
                )
        if bops:
            work_claim_specs.append(
                {
                    "label": "“Any earnings to share?”",
                    "next_node": None,
                    "end": True,
                    "grant_bops": bops,
                    "action": f"tinytown_claim:{npc_id}:{bucket}:bops",
                }
            )
        if getattr(record, "job_id", "") == "artist":
            work_claim_specs.append(
                {
                    "label": "“Hang the painting in the market!”",
                    "next_node": None,
                    "end": True,
                    "action": f"tinytown_claim:{npc_id}:{bucket}:art",
                }
            )
        if getattr(record, "job_id", "") == "comedian":
            work_claim_specs.append(
                {
                    "label": "“Give us your best routine!”",
                    "next_node": None,
                    "end": True,
                    "action": f"tinytown_claim:{npc_id}:{bucket}:routine",
                }
            )
    work_intro = f"“As {job_label_text}? {job_description_text} Right now: {job_gate_blurb}”"
    work_specs: list[dict] = []
    if job_state == "ready" and work_claim_specs:
        work_specs.append({"label": "“Show me what you've got!”", "next_node": claim_node_id})
    if job_state != "ready":
        work_specs.append({"label": "Anything ready for me?", "next_node": "work_wait"})
    work_specs.append({"label": "Ask about something else.", "next_node": "start"})
    add("work", work_intro, choices_for("work", work_specs))
    if job_state == "ready" and work_claim_specs:
        add(
            claim_node_id,
            "“Here — made with love and mild chaos.”",
            choices_for(claim_node_id, work_claim_specs),
        )
    if job_state != "ready":
        add(
            "work_wait",
            f"“Nothing quite ready yet — {job_gate_blurb.lower()} Come back later and ask me again!”",
            choices_for("work_wait", [{"label": "Back to work talk.", "next_node": "work"}]),
        )
    add(
        "chat",
        f"“Ooh, chatting. My favourite.” {name} settles in. “Pick a topic.”",
        choices_for(
            "chat",
            [
                {"label": f"Talk {likes_label}.", "next_node": "chat_topic"},
                {"label": "Ask for a house story.", "next_node": "chat_story"},
                {"label": "Say goodbye.", "next_node": "goodbye"},
            ],
        ),
    )
    add(
        "chat_topic",
        f"“{likes_label.capitalize()} is the best topic and I will not be taking questions. …Unless they're good questions.”",
        choices_for(
            "chat_topic",
            [
                {"label": "“Tell me everything.”", "next_node": "chat", "vibe_delta": 2, "repeatable": True},
                {"label": f"“Actually {likes_label} bores me.”", "next_node": "chat", "vibe_delta": -2, "repeatable": True},
            ],
        ),
    )
    add(
        "chat_story",
        "“So there I was, locked out of my own room, holding a kettle, at midnight. The kettle remembers. I remember. We don't speak of it.”",
        choices_for(
            "chat_story",
            [
                {"label": "“Tell it again!”", "next_node": "chat", "vibe_delta": 1, "repeatable": True},
                {"label": "Back to topics.", "next_node": "chat"},
            ],
        ),
    )
    add(
        "goodbye",
        f"“Always good talking to you.” {name} waves. “Come find me any time.”",
        choices_for("goodbye", [{"label": "Wave back.", "end": True, "repeatable": True}]),
    )

    return DialogDefinition(start_node_id="start", nodes=nodes)
