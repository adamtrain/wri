"""Stitch a book into a single Markdown manuscript."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from wri.book import CONFIG_FILE, Book, BookError
from wri.text import body, read_markdown, tidy_headings

_UNSAFE_IN_FILE_NAME = re.compile(r"\s*[/\\:]+\s*")
_LEADING_BLANK_LINES = re.compile(r"\A(?:[ \t]*\n)+")
_ROMAN = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)  # fmt: skip


@dataclass(frozen=True)
class Manuscript:
    """What compiling produced."""

    path: Path
    sections: int
    chapters: int
    words: int


def compile_book(book: Book) -> str:
    """The whole book as one Markdown document.

    Sections become ``#`` headings and chapters ``##`` headings. Headings inside
    chapters are moved down to fit underneath, starting at ``###``.
    """
    settings = book.settings
    blocks: list[str] = []
    metadata = [
        (key, value)
        for key, value in (
            ("title", settings.title),
            ("subtitle", settings.subtitle),
            ("author", settings.author),
        )
        if value
    ]
    if metadata:
        lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata]
        blocks.append("\n".join(["---", *lines, "---"]))

    number = 0
    for section_number, section in enumerate(book.sections, 1):
        blocks.append("# " + _heading(settings.section_heading, section_number, section.label))
        for chapter in section.chapters:
            number += 1
            blocks.append("## " + _heading(settings.chapter_heading, number, chapter.label))
            text = body(read_markdown(chapter.path))
            text = tidy_headings(text, top_level=3, title=chapter.title)
            text = _LEADING_BLANK_LINES.sub("", text).rstrip()
            if text:
                blocks.append(text)
    return "\n\n".join(blocks) + "\n"


def output_path(book: Book) -> Path:
    """Where the manuscript goes: ``output`` from wri.toml, or the book's title + ``.md``."""
    if book.settings.output:
        return book.root / Path(book.settings.output).expanduser()
    name = _UNSAFE_IN_FILE_NAME.sub(" - ", book.settings.title).strip(" .-") or "manuscript"
    return book.root / f"{name}.md"


def write_manuscript(book: Book, path: Path | None = None) -> Manuscript:
    """Compile the book and save it, replacing any earlier manuscript."""
    text = compile_book(book)
    path = path or output_path(book)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.partial")
        partial.write_text(text, encoding="utf-8")
        partial.replace(path)
    except OSError as error:
        raise BookError(f"Couldn't save the manuscript to {path}: {error.strerror}") from error
    return Manuscript(
        path=path,
        sections=len(book.sections),
        chapters=book.chapter_count,
        words=book.total_words(),
    )


def roman(number: int) -> str:
    """``number`` in Roman numerals, e.g. 14 → ``XIV``."""
    digits = []
    for value, numeral in _ROMAN:
        count, number = divmod(number, value)
        digits.append(numeral * count)
    return "".join(digits)


def _heading(template: str, number: int, title: str) -> str:
    try:
        heading = template.format(number=number, roman=roman(number), title=title)
    except (KeyError, IndexError, ValueError, AttributeError) as error:
        raise BookError(
            f"The heading format “{template}” in {CONFIG_FILE} doesn't work. "
            "Use {title}, {number} and {roman}."
        ) from error
    return " ".join(heading.split())
