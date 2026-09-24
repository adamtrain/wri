from pathlib import Path

import pytest

from wri.book import Book


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests away from the real config folder and the real editor."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)


@pytest.fixture
def book(tmp_path: Path) -> Book:
    return Book.create(tmp_path / "book", "Test Book")


def make_book(root: Path, outline: dict[str, dict[str, str]]) -> Book:
    """Create a book on disk from ``{section: {chapter: text}}``."""
    book = Book.create(root, "Test Book")
    for section_index, (section, chapters) in enumerate(outline.items()):
        book.add_section(section)
        for chapter_index, (chapter, text) in enumerate(chapters.items()):
            book.add_chapter(section_index, chapter)
            book.sections[section_index].chapters[chapter_index].path.write_text(text)
    book.reload()
    return book


def names(folder: Path) -> list[str]:
    """Everything visible in ``folder``, sorted."""
    return sorted(path.name for path in folder.iterdir() if not path.name.startswith("."))
