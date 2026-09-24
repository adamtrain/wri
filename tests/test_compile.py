from pathlib import Path

import pytest

from wri.book import CONFIG_FILE, BookError
from wri.compile import compile_book, output_path, roman, write_manuscript

from conftest import make_book


def test_compile_stitches_sections_and_chapters(tmp_path: Path) -> None:
    book = make_book(
        tmp_path / "book",
        {
            "Beginnings": {
                "Why Sleep": "# Why Sleep\n\nBecause.\n\n## A reason\n\nMore.\n",
                "Empty": "",
            },
            "Endings": {"Last": "---\nstatus: draft\n---\n\nThe end.\n\n\n"},
        },
    )
    assert compile_book(book) == (
        '---\ntitle: "Test Book"\n---\n\n'
        "# Beginnings\n\n"
        "## Why Sleep\n\nBecause.\n\n### A reason\n\nMore.\n\n"
        "## Empty\n\n"
        "# Endings\n\n"
        "## Last\n\nThe end.\n"
    )


def test_heading_formats(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "", "a2": ""}, "B": {"b1": ""}})
    (book.root / CONFIG_FILE).write_text(
        'title = "T"\nauthor = "Me"\n[compile]\n'
        'section_heading = "Part {roman}: {title}"\n'
        'chapter_heading = "Chapter {number}. {title}"\n'
    )
    book.reload()
    text = compile_book(book)
    assert 'author: "Me"' in text
    assert (
        "# Part I: A\n\n## Chapter 1. a1\n\n## Chapter 2. a2\n\n# Part II: B\n\n## Chapter 3. b1"
        in text
    )


def test_bad_heading_format(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {}})
    (book.root / CONFIG_FILE).write_text('[compile]\nsection_heading = "{chapter}"\n')
    book.reload()
    with pytest.raises(BookError, match="heading format"):
        compile_book(book)


def test_output_path(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {})
    (book.root / CONFIG_FILE).write_text('title = "Sleep: A Memoir / Part 1"\n')
    book.reload()
    assert output_path(book) == book.root / "Sleep - A Memoir - Part 1.md"
    (book.root / CONFIG_FILE).write_text('[compile]\noutput = "build/book.md"\n')
    book.reload()
    assert output_path(book) == book.root / "build" / "book.md"


def test_write_manuscript(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "one two", "a2": "three"}})
    result = write_manuscript(book)
    assert result.path == book.root / "Test Book.md"
    assert (result.sections, result.chapters, result.words) == (1, 2, 3)
    assert "## a2\n\nthree" in result.path.read_text()
    # The manuscript isn't mistaken for part of the book.
    book.reload()
    assert [section.title for section in book.sections] == ["A"]


def test_roman() -> None:
    assert [roman(n) for n in (1, 4, 9, 14, 40, 1994)] == ["I", "IV", "IX", "XIV", "XL", "MCMXCIV"]
