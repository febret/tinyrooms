"""Generate Scammon Academia lesson content from one authored topic table.

Emits, under ``worlds/scammon-academia``:

* ``cards/cards.yaml`` - nine subject skill cards plus ten topic cards each
* ``cards/bake.json`` - image-generation tasks for every card
* ``cutscenes.yaml`` - one room-audience cutscene per topic
* ``cutscenes/<topic-id>/<topic-id>.js`` - a tiny recipe wrapper per topic

Run with ``--art`` to also write square placeholder card art with Pillow, so
the world loads before the real bake runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD = REPO_ROOT / "worlds" / "scammon-academia"
CARDS_DIR = WORLD / "cards"
CUTSCENES_DIR = WORLD / "cutscenes"

SUBJECTS: tuple[tuple[str, str, str, str], ...] = (
    ("reading", "Reading", "#3f5a72", "#f4c430"),
    ("writing", "Writing", "#5a3f72", "#efc94c"),
    ("math", "Math", "#2f4470", "#6ad1e3"),
    ("history", "History", "#6b4a2f", "#e0b45a"),
    ("geography", "Geography", "#2f6b4a", "#8fe3a0"),
    ("chemistry", "Chemistry", "#3f2f5a", "#b78ce8"),
    ("tech", "Tech", "#1f3a4d", "#5ad0e0"),
    ("sport", "Sport", "#6b2f2f", "#f0a05a"),
    ("biology", "Biology", "#2f5a3f", "#8fe38f"),
)

# subject, slug, label, emoji, extra glyphs, motion, caption
TOPICS: tuple[tuple[str, str, str, str, tuple[str, ...], str, str], ...] = (
    ("reading", "alphabet", "Alphabet Adventure", "📖", ("🔤", "✏️"), "rise", "A is for adventure!"),
    ("reading", "phonics", "Phonics Pop", "🔤", ("🔊", "📣"), "pop", "Sound it out!"),
    ("reading", "sight-words", "Sight Words", "👀", ("📖", "✨"), "rise", "You know these by heart!"),
    ("reading", "story-time", "Story Time", "📚", ("🌙", "⭐"), "sweep", "Once upon a time..."),
    ("reading", "rhyming", "Rhyme Time", "🎵", ("🥁", "🎶"), "pop", "Cat, hat, bat!"),
    ("reading", "comprehension", "Comprehension", "🧠", ("❓", "💡"), "orbit", "What did the story mean?"),
    ("reading", "poetry", "Poetry Corner", "🪶", ("📜", "🌹"), "rise", "Words that float and sing."),
    ("reading", "fairy-tales", "Fairy Tales", "🧚", ("🏰", "✨"), "pop", "Happily ever after."),
    ("reading", "vocabulary", "Big Vocabulary", "💬", ("📖", "🔤"), "rain", "A brand new word!"),
    ("reading", "book-clubs", "Book Club", "🗣️", ("📚", "😊"), "sweep", "Everyone shares a title."),
    ("writing", "handwriting", "Neat Handwriting", "✍️", ("📝", "📄"), "rise", "Loops and lines."),
    ("writing", "spelling", "Spelling Bee", "🐝", ("🔤", "🏆"), "pop", "S-P-E-L-L!"),
    ("writing", "sentences", "Great Sentences", "📝", ("📄", "✅"), "sweep", "Start with a capital."),
    ("writing", "punctuation", "Punctuation Power", "❗", ("❓", "…"), "pop", "Stop, pause, or shout!"),
    ("writing", "paragraphs", "Paragraph Builder", "📄", ("🧱", "📝"), "rise", "One idea per paragraph."),
    ("writing", "storytelling", "Storytelling", "🌟", ("📖", "🎭"), "orbit", "Give your tale a hero."),
    ("writing", "letters", "Friendly Letters", "📮", ("✉️", "💌"), "rain", "Dear reader..."),
    ("writing", "journaling", "Journaling", "📔", ("🖊️", "💭"), "pop", "Today I learned..."),
    ("writing", "grammar", "Grammar Puzzle", "🧩", ("🔤", "✅"), "sweep", "Nouns, verbs, and fun."),
    ("writing", "creative-writing", "Creative Writing", "🖋️", ("🌈", "💡"), "rise", "Imagine it, then write it."),
    ("math", "counting", "Count With Me", "🔢", ("1️⃣", "2️⃣"), "rise", "One, two, three!"),
    ("math", "addition", "Addition Action", "➕", ("🔢", "🎯"), "pop", "Add it all up!"),
    ("math", "subtraction", "Subtraction Slide", "➖", ("🔢", "📉"), "pop", "Take some away!"),
    ("math", "multiplication", "Times Tables", "✖️", ("🔢", "⚡"), "orbit", "Groups of numbers."),
    ("math", "division", "Division Dash", "➗", ("🍕", "🎯"), "sweep", "Share it fairly!"),
    ("math", "fractions", "Fraction Slices", "🍕", ("🥧", "🔢"), "pop", "Half, third, quarter!"),
    ("math", "shapes", "Shape Safari", "🔺", ("⭕", "🟦"), "rise", "Count the corners."),
    ("math", "measurement", "Measuring Things", "📏", ("📐", "⚖️"), "sweep", "How long is it?"),
    ("math", "time", "Telling Time", "⏰", ("🕐", "🔔"), "orbit", "Tick tock, what o'clock?"),
    ("math", "word-problems", "Word Problems", "🧮", ("💭", "✅"), "pop", "Read, think, solve."),
    ("history", "ancient-egypt", "Ancient Egypt", "🏺", ("🐫", "☀️"), "rise", "Along the river Nile."),
    ("history", "knights", "Knights & Castles", "🛡️", ("⚔️", "🏰"), "pop", "A code of honor."),
    ("history", "vikings", "Viking Voyages", "⚔️", ("⛵", "🌊"), "sweep", "Across the cold sea."),
    ("history", "explorers", "Brave Explorers", "🧭", ("🗺️", "⛵"), "orbit", "To the edge of the map."),
    ("history", "castles", "Castle Life", "🏰", ("👑", "🛡️"), "rain", "Drawbridge down!"),
    ("history", "ancient-rome", "Ancient Rome", "🏛️", ("🏺", "⚔️"), "rise", "All roads lead there."),
    ("history", "revolution", "Revolutions", "🎺", ("📜", "🔥"), "pop", "People demand change."),
    ("history", "pioneers", "Pioneers", "🛖", ("🌾", "🐎"), "sweep", "Westward, ho!"),
    ("history", "pharaohs", "Pharaohs", "🐍", ("👑", "🏺"), "rise", "Rulers of the sand."),
    ("history", "timelines", "Timelines", "⏳", ("📜", "➡️"), "orbit", "First this, then that."),
    ("geography", "continents", "Seven Continents", "🌍", ("🗺️", "🧭"), "rise", "The whole wide world."),
    ("geography", "oceans", "Oceans Deep", "🌊", ("🐟", "🐋"), "sweep", "Down to the deep!"),
    ("geography", "mountains", "Mighty Mountains", "⛰️", ("🏔️", "🧗"), "pop", "Up above the clouds."),
    ("geography", "rivers", "Rivers Run", "🏞️", ("💧", "🌉"), "rise", "From source to sea."),
    ("geography", "deserts", "Deserts", "🏜️", ("🌵", "☀️"), "rain", "Dry and vast."),
    ("geography", "capitals", "Capital Cities", "🏙️", ("🌆", "📍"), "orbit", "Every country has one."),
    ("geography", "maps", "Reading Maps", "🗺️", ("🧭", "📍"), "sweep", "North, south, east, west."),
    ("geography", "climates", "Climates", "🌦️", ("🌨️", "☀️"), "pop", "Weather all year round."),
    ("geography", "volcanoes", "Volcanoes", "🌋", ("🔥", "🪨"), "pop", "Boom! Lava flows."),
    ("geography", "landmarks", "World Landmarks", "🗽", ("🗼", "🌉"), "rise", "Famous spots to see."),
    ("chemistry", "atoms", "Tiny Atoms", "⚛️", ("🔬", "✨"), "orbit", "The building blocks."),
    ("chemistry", "molecules", "Molecules", "🧬", ("⚛️", "🔗"), "pop", "Atoms holding hands."),
    ("chemistry", "reactions", "Reactions", "🧪", ("💥", "🫧"), "pop", "Mix and watch!"),
    ("chemistry", "acids-bases", "Acids & Bases", "🍋", ("🧪", "⚖️"), "sweep", "Sour or slippery?"),
    ("chemistry", "periodic-table", "Periodic Table", "🔬", ("🧪", "🔢"), "rise", "Every element in place."),
    ("chemistry", "mixtures", "Mixtures", "🥣", ("🧪", "🌀"), "rain", "Stir it together!"),
    ("chemistry", "gases", "Gases", "💨", ("🎈", "🫧"), "rise", "Invisible but real."),
    ("chemistry", "crystals", "Crystals", "💎", ("❄️", "✨"), "pop", "Growing shapes."),
    ("chemistry", "solutions", "Solutions", "🧫", ("💧", "🧪"), "orbit", "Dissolved and clear."),
    ("chemistry", "safe-lab", "Lab Safety", "🥽", ("🧪", "⚠️"), "sweep", "Goggles on first!"),
    ("tech", "coding", "Coding", "💻", ("⌨️", "🐛"), "rise", "Hello, world!"),
    ("tech", "robots", "Robots", "🤖", ("⚙️", "🔧"), "pop", "Beep boop, I learn."),
    ("tech", "internet", "The Internet", "🌐", ("🔗", "💻"), "orbit", "Worlds connected."),
    ("tech", "circuits", "Circuits", "🔌", ("💡", "⚡"), "sweep", "Close the loop!"),
    ("tech", "rockets", "Rockets", "🚀", ("🌟", "🛰️"), "rise", "Three... two... one!"),
    ("tech", "ai", "Friendly AI", "🧠", ("🤖", "💡"), "orbit", "Teaching machines to think."),
    ("tech", "3d-printing", "3D Printing", "🖨️", ("🧱", "📦"), "pop", "Layer by layer."),
    ("tech", "keyboards", "Keyboards", "⌨️", ("💻", "⌨️"), "rain", "Type, type, type!"),
    ("tech", "cybersecurity", "Cyber Safety", "🔒", ("🛡️", "🔑"), "pop", "Keep passwords secret."),
    ("tech", "solar-power", "Solar Power", "☀️", ("🔋", "🌞"), "rise", "Power from the sun."),
    ("sport", "soccer", "Soccer", "⚽", ("🥅", "🏃"), "pop", "Pass and score!"),
    ("sport", "basketball", "Basketball", "🏀", ("🎯", "👟"), "pop", "Swish!"),
    ("sport", "running", "Running", "🏃", ("💨", "👟"), "sweep", "On your marks..."),
    ("sport", "swimming", "Swimming", "🏊", ("🌊", "🥇"), "rise", "Kick, kick, breathe."),
    ("sport", "gymnastics", "Gymnastics", "🤸", ("⭐", "🎀"), "orbit", "Balance and tumble."),
    ("sport", "yoga", "Yoga", "🧘", ("🌿", "🕊️"), "rise", "Breathe in, breathe out."),
    ("sport", "tennis", "Tennis", "🎾", ("🏆", "🥅"), "pop", "Forehand!"),
    ("sport", "cycling", "Cycling", "🚴", ("💨", "🛞"), "sweep", "Pedal to the finish."),
    ("sport", "team-spirit", "Team Spirit", "📣", ("🤝", "🏅"), "rain", "Gooo team!"),
    ("sport", "warm-ups", "Warm Ups", "💪", ("🤸", "🔥"), "rise", "Stretch before you play."),
    ("biology", "cells", "Cells", "🔬", ("🧫", "🧬"), "orbit", "The smallest life."),
    ("biology", "plants", "Plants", "🌱", ("🍃", "🌸"), "rise", "Sprout and grow."),
    ("biology", "animals", "Animals", "🦁", ("🐘", "🦜"), "pop", "Wild and wonderful."),
    ("biology", "ecosystems", "Ecosystems", "🌳", ("🦌", "🐦"), "sweep", "Everything connected."),
    ("biology", "photosynthesis", "Photosynthesis", "🌞", ("🍃", "💧"), "rise", "Sunlight becomes food."),
    ("biology", "human-body", "Human Body", "🫀", ("🦴", "🧠"), "pop", "Amazing machine."),
    ("biology", "insects", "Insects", "🐞", ("🐜", "🦋"), "rain", "Six little legs."),
    ("biology", "dinosaurs", "Dinosaurs", "🦕", ("🦖", "🌿"), "pop", "Long ago giants."),
    ("biology", "food-chains", "Food Chains", "🍎", ("🐭", "🦅"), "orbit", "Who eats whom."),
    ("biology", "habitats", "Habitats", "🏝️", ("🐠", "🌲"), "sweep", "Homes all around."),
)


def _subject_index(subject_id: str) -> int:
    for index, (sid, *_rest) in enumerate(SUBJECTS):
        if sid == subject_id:
            return index
    raise KeyError(subject_id)


def _subject_label(subject_id: str) -> str:
    for sid, label, *_rest in SUBJECTS:
        if sid == subject_id:
            return label
    raise KeyError(subject_id)


def _subject_colors(subject_id: str) -> tuple[str, str]:
    for sid, _label, bg, accent in SUBJECTS:
        if sid == subject_id:
            return bg, accent
    raise KeyError(subject_id)


def _topic_id(subject_id: str, slug: str) -> str:
    return f"topic-{subject_id}-{slug}"


def _yscalar(text: str) -> str:
    """Return a YAML-safe double-quoted scalar (JSON strings are valid YAML)."""

    return json.dumps(str(text))


def write_cards() -> None:
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# Generated by tools/generate_scammon_lessons.py", ""]
    for subject_id, label, _bg, _accent in SUBJECTS:
        card_id = f"skill-{subject_id}"
        lines += [
            f"{card_id}:",
            f"  label: {_yscalar(f'{label} Skill')}",
            f"  description: {_yscalar(f'Teaches you how to run {label} topics for your class.')}",
            f"  image: {card_id}.png",
            "  type: skill",
            "  rank: Script Kiddo",
            "  rarity: Common",
            "",
        ]
    for subject_id, slug, label, _emoji, _glyphs, _motion, _line in TOPICS:
        card_id = _topic_id(subject_id, slug)
        lines += [
            f"{card_id}:",
            f"  label: {_yscalar(label)}",
            f"  description: {_yscalar(f'A {_subject_label(subject_id)} topic you can teach your class.')}",
            f"  image: {card_id}.png",
            "  type: item",
            "  rarity: Common",
            "  energy_cost: 10",
            f"  cutscene: {card_id}",
            f"  tags: [topic, subject:{subject_id}, skill:skill-{subject_id}]",
            "",
        ]
    (CARDS_DIR / "cards.yaml").write_text("\n".join(lines), encoding="utf-8")


def write_cutscenes() -> None:
    CUTSCENES_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# Generated by tools/generate_scammon_lessons.py", ""]
    for subject_id, slug, label, _emoji, _glyphs, _motion, _line in TOPICS:
        scene_id = _topic_id(subject_id, slug)
        lines += [
            f"{scene_id}:",
            f"  title: {_yscalar(label)}",
            f"  script: {scene_id}.js",
            "  frame: movie",
            "  duration: 3200",
            "  audience: room",
            "  room_bound: true",
            "",
        ]
    lines += [
        "lesson-test:",
        "  title: Class Test",
        "  script: lesson-test.js",
        "  frame: movie",
        "  duration: 12000",
        "  audience: room",
        "  room_bound: true",
        "  params:",
        "    stage_background: '#0b2545'",
        "",
    ]
    (WORLD / "cutscenes.yaml").write_text("\n".join(lines), encoding="utf-8")


def write_scene_modules() -> None:
    import json as _json

    for subject_id, slug, label, emoji, glyphs, motion, line in TOPICS:
        scene_id = _topic_id(subject_id, slug)
        bg, accent = _subject_colors(subject_id)
        duration = 2600 + (len(label) % 4) * 300
        recipe = {
            "emoji": emoji,
            "glyphs": list(glyphs) + [emoji],
            "motion": motion,
            "bg": bg,
            "accent": accent,
            "line": line,
            "title": label,
            "duration": duration,
        }
        module_dir = CUTSCENES_DIR / scene_id
        module_dir.mkdir(parents=True, exist_ok=True)
        source = (
            "// Generated by tools/generate_scammon_lessons.py\n"
            'import { runTopicScene } from "../_topic/engine.js";\n\n'
            f"const RECIPE = {_json.dumps(recipe)};\n\n"
            "export default function (ctx) {\n"
            "  return runTopicScene(ctx, RECIPE);\n"
            "}\n"
        )
        (module_dir / f"{scene_id}.js").write_text(source, encoding="utf-8")


PACK_BACK = "academia-pack-back.png"
PACK_PRICE = 12
PACK_SIZE = 3

# Qwen-Image-2.1 (the default imagegen workflow) reads natural-language,
# descriptive prompts rather than tag soup, and ignores the negative prompt at
# cfg 1. A shared style phrase and an explicit "no text" keep card art clean.
QWEN_STYLE = "flat vector illustration, clean bold shapes, cheerful children's picture-book style"
# Qwen-Image renders typography well, so text must be excluded explicitly.
NO_TEXT = "no text, no letters, no words, no numbers, no captions, no labels, no watermark, textless image"

# Plain visual descriptions of each subject's imagery, used only to describe
# the picture itself in bake prompts.
SUBJECT_MOTIFS: dict[str, str] = {
    "reading": "an open storybook with a golden bookmark",
    "writing": "a pencil writing on lined paper",
    "math": "bright numbers beside a plus and a minus sign",
    "history": "a rolled scroll and an hourglass",
    "geography": "a globe with green continents and blue oceans",
    "chemistry": "a bubbling round flask and two test tubes",
    "tech": "a small laptop beside a toy robot",
    "sport": "a soccer ball beside a silver whistle",
    "biology": "a green leaf and an orange butterfly",
}


def write_packs() -> None:
    lines: list[str] = ["# Generated by tools/generate_scammon_lessons.py", ""]
    for subject_id, label, _bg, _accent in SUBJECTS:
        card_ids = [f"skill-{subject_id}"] + [
            _topic_id(subject_id, slug)
            for sid, slug, *_rest in TOPICS
            if sid == subject_id
        ]
        cards = ", ".join(card_ids)
        lines += [
            f"scammon-{subject_id}:",
            f"  label: {_yscalar(f'Scammon Academia: {label}')}",
            f"  description: {_yscalar(f'A Scammon Academia pack with the {label} Skill and a batch of {label} topics to teach.')}",
            f"  back_image: {PACK_BACK}",
            f"  price: {PACK_PRICE}",
            f"  size: {PACK_SIZE}",
            f"  cards: [{cards}]",
            f"  guaranteed: [skill-{subject_id}]",
            "",
        ]
    (CARDS_DIR / "packs.yaml").write_text("\n".join(lines), encoding="utf-8")


def write_bake() -> None:
    tasks = [
        {
            "label": "academia-pack-back",
            "tool": "image",
            "prompt": (
                "a symmetrical collectible card back with a smiling gray husky dog crest inside a "
                "yellow circle on a deep blue field framed by a thin yellow border, "
                f"{QWEN_STYLE}, {NO_TEXT}"
            ),
            "output": str(CARDS_DIR / PACK_BACK).replace("\\", "/"),
            "args": {"width": 768, "height": 1152, "seed": 89999, "steps": 25},
        },
    ]
    seed = 90000
    for subject_id, label, _bg, _accent in SUBJECTS:
        card_id = f"skill-{subject_id}"
        motif = SUBJECT_MOTIFS.get(subject_id, "school supplies")
        tasks.append(
            {
                "label": card_id,
                "tool": "image",
                "prompt": (
                    f"a centered school emblem for the {label} subject showing {motif}, "
                    f"{QWEN_STYLE}, blue and yellow school colors on a plain deep blue background, {NO_TEXT}"
                ),
                "output": str(CARDS_DIR / f"{card_id}.png").replace("\\", "/"),
                "args": {"width": 768, "height": 768, "seed": seed, "steps": 25},
            }
        )
        seed += 1
    for subject_id, slug, label, _emoji, _glyphs, _motion, _line in TOPICS:
        card_id = _topic_id(subject_id, slug)
        motif = SUBJECT_MOTIFS.get(subject_id, "a classroom scene")
        tasks.append(
            {
                "label": card_id,
                "tool": "image",
                "prompt": (
                    f"a cheerful children's textbook illustration about {label} for a "
                    f"{_subject_label(subject_id)} lesson, showing {motif}, "
                    f"{QWEN_STYLE}, plain light background, {NO_TEXT}"
                ),
                "output": str(CARDS_DIR / f"{card_id}.png").replace("\\", "/"),
                "args": {"width": 768, "height": 768, "seed": seed, "steps": 25},
            }
        )
        seed += 1
    document = {"tasks": tasks}
    (CARDS_DIR / "bake.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def write_placeholder_art() -> None:
    from PIL import Image, ImageDraw, ImageFont

    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    size = 256

    def render(card_id: str, bg: str, accent: str, title: str) -> None:
        image = Image.new("RGB", (size, size), bg)
        draw = ImageDraw.Draw(image)
        draw.ellipse([28, 28, size - 28, size - 28], outline=accent, width=8)
        words = title.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) > size - 56 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        total = len(lines) * 40
        y = (size - total) / 2
        for line in lines:
            width = draw.textlength(line, font=font)
            draw.text(((size - width) / 2, y), line, fill=accent, font=font)
            y += 40
        image.save(CARDS_DIR / f"{card_id}.png")

    for subject_id, label, bg, accent in SUBJECTS:
        render(f"skill-{subject_id}", bg, accent, f"{label} Skill")
    for subject_id, slug, label, _emoji, _glyphs, _motion, _line in TOPICS:
        bg, accent = _subject_colors(subject_id)
        render(_topic_id(subject_id, slug), bg, accent, label)

    back = Image.new("RGB", (384, 576), "#1f3a72")
    draw = ImageDraw.Draw(back)
    draw.rounded_rectangle([24, 24, 360, 552], radius=24, outline="#f4c430", width=10)
    draw.ellipse([132, 150, 252, 270], outline="#f4c430", width=10)
    caption = "SCAMMON\nACADEMIA"
    y = 360
    for line in caption.split("\n"):
        width = draw.textlength(line, font=font)
        draw.text(((384 - width) / 2, y), line, fill="#f4c430", font=font)
        y += 44
    back.save(CARDS_DIR / PACK_BACK)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art", action="store_true", help="also write placeholder card art")
    args = parser.parse_args()
    write_cards()
    write_cutscenes()
    write_scene_modules()
    write_packs()
    write_bake()
    if args.art:
        write_placeholder_art()
    print(f"generated {len(SUBJECTS)} skill cards and {len(TOPICS)} topic cards")


if __name__ == "__main__":
    main()
