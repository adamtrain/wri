"""Regenerate the screenshots in docs/ from a made-up sample book.

    uv run scripts/screenshots.py

Each scene opens wri on a fresh copy of the sample book with Textual's test
pilot, presses a few keys and saves the screen as an SVG. Unchanged scenes
produce identical files, so `git status` shows which screenshots changed.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.pilot import Pilot

from wri.app import PREVIEW_DELAY, WriApp
from wri.book import CONFIG_FILE, Book

DOCS = Path(__file__).resolve().parent.parent / "docs"
WIDTH = 100

TIRED_CENTURY = """\
# The Tired Century

Somewhere around 1900 we started going to bed later, and we never really
stopped. The electric light did not invent the late night, but it made the late
night cheap, and anything cheap soon becomes normal.

## Lamps and lies

For most of history darkness was expensive. Candles cost money, lamp oil cost
more, and a household that stayed up past nine was rich, ill, or up to
something. Night was a thing you got through, usually asleep.

> The night is for sleeping; the day is for pretending you did.

Three things changed the arithmetic:

- the light bulb, which turned evenings into a second afternoon,
- the factory whistle, which set waking hours by someone else's clock,
- and the radio, which gave everyone a reason to wait up for the news.
"""

OPENINGS = {
    "What We Lose at Night": """\
Ask people what sleep is for and most will say *rest*, as if the body were a
phone left on its charger. The truth is busier. While you sleep your brain
files the day away, your immune system takes stock, and your blood pressure
gets its only real holiday.
""",
    "A History of the Bed": """\
The oldest bed anyone has found is about seventy-seven thousand years old: a
mat of sedges and rushes in a South African cave, laid over with leaves that
kept the insects away. Beds have been getting softer and more expensive ever
since, though not obviously better.
""",
    "Circadian Clocks": """\
Every cell in your body keeps time. Not perfectly, and not alone, but it keeps
time: a loop of genes switching one another on and off that takes roughly a day
to come back round.

## Living without windows

Put people in a room with no clocks and no daylight and they drift, going to
bed a little later each day. Morning light is what pulls them back.
""",
    "Deep Sleep and Memory": """\
In the deepest stage of sleep the brain looks, on a chart, almost idle: slow,
rolling waves, about one a second. It is anything but idle. Those waves are the
sound of the day being replayed and sorted, the useful kept and the rest let go.
""",
    "What Dreams Are For": """\
Every theory of dreaming explains some dreams beautifully and the rest not at
all. Dreams are rehearsal, or housekeeping, or noise the brain tries to make a
story out of. Probably they are all three, depending on the night.
""",
    "Coffee, Reconsidered": """\
Caffeine does not give you energy. It borrows it. All day a chemical builds up
in the brain that says, more and more insistently, *time for bed*; caffeine
simply covers its ears. The debt is still there when the cup is empty.
""",
    "Night Shifts": """\
Something like one worker in five works outside the ordinary day: nurses,
bakers, pilots, the people who keep the trains and the power running. They are
asking their bodies to do the one thing a body is built not to do.
""",
}

# More text to make the word counts look like a book in progress. It sits below
# the part of each chapter that the screenshots show.
FILLER = [
    "The research here is younger than you might think, and messier. Most of what "
    "we know comes from small studies of volunteers sleeping in laboratories.",
    "Still, the broad picture has held up for decades. Short nights add up, the "
    "body keeps count, and there is no clever trick that turns five hours into eight.",
    "What changes from person to person is the timing. Some of us are built for "
    "early mornings and some for late nights, and neither is a moral failing.",
]

# Section → chapter → roughly how many words it has so far (0: not started).
OUTLINE: dict[str, dict[str, int]] = {
    "The Problem": {
        "The Tired Century": 4210,
        "What We Lose at Night": 3640,
        "A History of the Bed": 2980,
    },
    "The Science": {
        "Circadian Clocks": 3905,
        "Deep Sleep and Memory": 2410,
        "What Dreams Are For": 1730,
        "The Adenosine Story": 0,
    },
    "In Practice": {
        "Coffee, Reconsidered": 2120,
        "Night Shifts": 980,
        "Tiny Alarm Clocks": 0,
    },
    "Afterword": {},
}


def make_sample_book(root: Path) -> None:
    """Write the sample book into ``root``, which shouldn't exist yet."""
    book = Book.create(root, "The Quiet Hours")
    config = root / CONFIG_FILE
    config.write_text(config.read_text().replace("# target = 60000", "target = 60000"))
    for section_index, (section, chapters) in enumerate(OUTLINE.items()):
        book.add_section(section)
        for chapter_index, (chapter, words) in enumerate(chapters.items()):
            book.add_chapter(section_index, chapter)
            if words:
                text = TIRED_CENTURY if chapter == "The Tired Century" else OPENINGS[chapter]
                path = book.sections[section_index].chapters[chapter_index].path
                path.write_text(_lengthen(text, words))


def _lengthen(text: str, words: int) -> str:
    paragraphs = [text.rstrip()]
    count = len(text.split())
    for paragraph in itertools.cycle(FILLER):
        if count >= words:
            break
        paragraphs.append(paragraph)
        count += len(paragraph.split())
    return "\n\n".join(paragraphs) + "\n"


# Scenes: what to press before taking each screenshot.

type Scene = Callable[[Pilot], Awaitable[None]]


async def hero(pilot: Pilot) -> None:
    await pilot.press("enter")


async def new_chapter(pilot: Pilot) -> None:
    await pilot.press("end", "up", "enter", "down", "n")
    for word in ["Early", "Birds", "and", "Night", "Owls"]:
        await pilot.press(*word, "space")
    await pilot.press("backspace")


async def move_chapter(pilot: Pilot) -> None:
    await pilot.press("down", "enter", "end", "m", "down")


async def compile_light(pilot: Pilot) -> None:
    pilot.app.theme = "catppuccin-latte"
    await pilot.press("down", "enter", "down", "c")


SCENES: dict[str, tuple[Scene, int]] = {
    "hero": (hero, 30),
    "new-chapter": (new_chapter, 24),
    "move-chapter": (move_chapter, 24),
    "compile-light": (compile_light, 30),
}


# GitHub shows README images in a sandbox where the SVG's web font can't load,
# so name good local monospace fonts to fall back on instead of the default.
FONT_FALLBACKS = 'ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace'


async def capture(book: Path, scene: Scene, height: int) -> str:
    app = WriApp(book)
    async with app.run_test(size=(WIDTH, height), notifications=True) as pilot:
        await pilot.pause(0.3)
        await scene(pilot)
        await pilot.pause(PREVIEW_DELAY * 5)
        svg = app.export_screenshot(title="wri")
    return svg.replace(
        "font-family: Fira Code, monospace;", f'font-family: "Fira Code", {FONT_FALLBACKS};'
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["XDG_CONFIG_HOME"] = scratch  # leave the real theme choice alone
        for name, (scene, height) in SCENES.items():
            book = Path(scratch) / name / "The Quiet Hours"
            make_sample_book(book)
            svg = DOCS / f"{name}.svg"
            svg.write_text(asyncio.run(capture(book, scene, height)))
            print(f"{svg.relative_to(DOCS.parent)}  {svg.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
