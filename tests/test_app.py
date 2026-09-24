"""Drive the TUI the way a writer would, and check what ends up on disk."""

import contextlib
import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Input, Static

from wri.app import BookScreen, WriApp
from wri.book import CONFIG_FILE, TRASH_DIR, Book
from wri.dialogs import Confirm, HelpScreen, SectionPicker, TextPrompt

from conftest import make_book, names

SIZE = (130, 36)


@pytest.fixture
def editor(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Stand in for the writer's editor: note each file opened and add a sentence to it."""
    opened: list[Path] = []

    def run_editor(command: str, path: Path) -> int:
        opened.append(path)
        with path.open("a") as file:
            file.write("\nWords written in the editor.\n")
        return 0

    monkeypatch.setenv("EDITOR", "my-editor")
    monkeypatch.setattr("wri.app.run_editor", run_editor)
    monkeypatch.setattr(WriApp, "suspend", lambda self: contextlib.nullcontext())
    return opened


@pytest.fixture
def book(tmp_path: Path) -> Book:
    return make_book(
        tmp_path / "book",
        {
            "Beginning": {"First": "One two three.", "Second": "Four five."},
            "Middle": {"Third": "Six."},
            "End": {},
        },
    )


def screen(pilot: Pilot) -> BookScreen:
    assert isinstance(pilot.app.screen, BookScreen)
    return pilot.app.screen


async def answer(pilot: Pilot, text: str) -> None:
    """Type ``text`` into the open prompt and press enter."""
    await pilot.pause()
    assert isinstance(pilot.app.screen, TextPrompt)
    pilot.app.screen.query_one(Input).value = text
    await pilot.press("enter")
    await pilot.pause()


async def eventually(pilot: Pilot, check: Callable[[], bool], timeout: float = 5) -> None:
    """Wait until ``check()`` is true, e.g. for the preview to catch up after its short delay."""
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "the screen didn't catch up in time"
        await pilot.pause(0.05)


def shown_title(widget: Widget) -> str:
    """The border title exactly as drawn (the public getter returns it as markup)."""
    title = widget._border_title
    return title.plain if title else ""


def text_of(pilot: Pilot, selector: str) -> str:
    return str(pilot.app.screen.query_one(selector, Static).content)


async def test_shows_the_book(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await eventually(pilot, lambda: view.preview.source == "One two three.")
        assert view.sections_list.option_count == 3
        assert view.section_index == 0
        assert view.chapter is not None and view.chapter.title == "First"
        assert text_of(pilot, "#book-words") == "6 words"
        assert "3 sections · 3 chapters" in text_of(pilot, "#book-counts")
        await pilot.press("down")
        await pilot.pause()
        assert view.chapter is not None and view.chapter.title == "Third"


async def test_welcomes_an_empty_book(tmp_path: Path) -> None:
    book = Book.create(tmp_path / "empty")
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await eventually(pilot, lambda: "Welcome to wri" in view.preview.source)
        assert view.section is None


async def test_add_a_section_after_the_current_one(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("n")
        await answer(pilot, "  An   Interlude ")
        assert names(book.root) == [
            "01 Beginning",
            "02 An Interlude",
            "03 Middle",
            "04 End",
            CONFIG_FILE,
        ]
        assert screen(pilot).section_index == 1


async def test_a_bad_title_is_explained_not_saved(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("n")
        await answer(pilot, "Before/After")
        assert isinstance(pilot.app.screen, TextPrompt)
        assert "/" in text_of(pilot, ".error")
        await pilot.press("escape")
        await pilot.pause()
        assert names(book.root) == ["01 Beginning", "02 Middle", "03 End", CONFIG_FILE]


async def test_rename_a_section(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("down", "r")
        await pilot.pause()
        assert pilot.app.screen.query_one(Input).value == "Middle"
        assert text_of(pilot, ".description") == "→ 02 Middle/"
        await answer(pilot, "The Middle")
        assert names(book.root) == ["01 Beginning", "02 The Middle", "03 End", CONFIG_FILE]
        assert (book.root / "02 The Middle" / "01 Third.md").read_text() == "Six."


async def test_move_sections(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("shift+down")
        await pilot.pause()
        assert names(book.root) == ["01 Middle", "02 Beginning", "03 End", CONFIG_FILE]
        assert screen(pilot).section_index == 1
        await pilot.press("J", "J")
        await pilot.pause()
        assert names(book.root) == ["01 Middle", "02 End", "03 Beginning", CONFIG_FILE]
        assert screen(pilot).section_index == 2
        await pilot.press("K")
        await pilot.pause()
        assert names(book.root) == ["01 Middle", "02 Beginning", "03 End", CONFIG_FILE]


async def test_delete_asks_first(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(pilot.app.screen, Confirm)
        await pilot.press("n")
        await pilot.pause()
        assert names(book.root) == ["01 Beginning", "02 Middle", "03 End", CONFIG_FILE]

        await pilot.press("end", "d", "y")
        await pilot.pause()
        assert names(book.root) == ["01 Beginning", "02 Middle", CONFIG_FILE]
        assert screen(pilot).section_index == 1
        assert list((book.root / TRASH_DIR).glob("*/03 End"))


async def test_new_chapter_opens_the_editor(book: Book, editor: list[Path]) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("enter", "n")
        await pilot.pause()
        assert text_of(pilot, ".description") == ""
        pilot.app.screen.query_one(Input).value = "Fresh"
        await pilot.pause()
        assert text_of(pilot, ".description") == "→ 02 Fresh.md"
        await answer(pilot, "Fresh Start")
        section = book.root / "01 Beginning"
        assert names(section) == ["01 First.md", "02 Fresh Start.md", "03 Second.md"]
        assert editor == [section / "02 Fresh Start.md"]
        view = screen(pilot)
        assert view.chapter is not None and view.chapter.title == "Fresh Start"
        assert view.book.words(view.chapter) == 5
        assert pilot.app.focused is view.chapters_list


async def test_edit_a_chapter(book: Book, editor: list[Path]) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("enter", "down", "enter")
        view = screen(pilot)
        await eventually(pilot, lambda: "Words written in the editor." in view.preview.source)
        chapter = book.root / "01 Beginning" / "02 Second.md"
        assert editor == [chapter]
        assert chapter.read_text() == "Four five.\nWords written in the editor.\n"
        assert text_of(pilot, "#book-words") == "11 words"


async def test_clicking_highlights_and_double_clicking_opens(
    book: Book, editor: list[Path]
) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await pilot.click("#chapters", offset=(6, 2))
        await pilot.pause()
        assert view.chapter is not None and view.chapter.title == "Second"
        assert editor == []
        await pilot.click("#chapters", offset=(6, 2), times=2)
        await pilot.pause()
        assert editor == [book.root / "01 Beginning" / "02 Second.md"]


async def test_move_chapters(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("enter", "shift+down")
        await pilot.pause()
        assert names(book.root / "01 Beginning") == ["01 Second.md", "02 First.md"]
        assert screen(pilot).chapter_index == 1

        await pilot.press("m")
        await pilot.pause()
        assert isinstance(pilot.app.screen, SectionPicker)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert names(book.root / "01 Beginning") == ["01 Second.md"]
        assert names(book.root / "03 End") == ["01 First.md"]
        view = screen(pilot)
        assert (view.section_index, view.chapter_index) == (2, 0)


async def test_escape_goes_back_to_the_sections(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await pilot.press("enter")
        assert pilot.app.focused is view.chapters_list
        await pilot.press("escape")
        assert pilot.app.focused is view.sections_list
        await pilot.press("right")
        assert pilot.app.focused is view.chapters_list


async def test_compile(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        manuscript = book.root / "Test Book.md"
        assert "# Middle\n\n## Third\n\nSix." in manuscript.read_text()
        assert any(n.title == "Compiled" for n in pilot.app._notifications)


async def test_notices_changes_made_elsewhere(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await pilot.press("down")
        (book.root / "00 Prologue").mkdir()
        (book.root / "02 Middle" / "01 Third.md").write_text("Six seven eight.")
        view.check_disk()
        await pilot.pause()
        assert view.sections_list.option_count == 4
        assert view.section is not None and view.section.title == "Middle"
        assert text_of(pilot, "#book-words") == "8 words"


async def test_reports_broken_settings(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        (book.root / CONFIG_FILE).write_text("title = ")
        screen(pilot).check_disk()
        await pilot.pause()
        assert any(CONFIG_FILE in n.title for n in pilot.app._notifications)


async def test_help_and_preview_toggle(book: Book) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(pilot.app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("p")
        assert screen(pilot).has_class("-no-preview")


async def test_remembers_the_theme(book: Book, tmp_path: Path) -> None:
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        pilot.app.theme = "nord"
        await pilot.pause()
    preferences = tmp_path / "config" / "wri" / "preferences.json"
    assert json.loads(preferences.read_text()) == {"theme": "nord"}
    assert WriApp(book.root).theme == "nord"


async def test_long_chapters_preview_briefly_until_you_read_them(tmp_path: Path) -> None:
    long_text = "\n\n".join(f"Paragraph {n}. " + "word " * 100 for n in range(40)).strip()
    book = make_book(tmp_path / "book", {"A": {"Long": long_text}})
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await eventually(pilot, lambda: view.preview.source.endswith("to read the rest here.*"))
        assert len(view.preview.source) < len(long_text)
        await pilot.press("tab", "tab")
        assert pilot.app.focused is view.preview_pane
        await eventually(pilot, lambda: view.preview.source == long_text)


async def test_titles_that_look_like_markup_are_shown_as_typed(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"[Draft] Notes": {"The [b]Unknown": "Text."}})
    async with WriApp(book.root).run_test(size=SIZE) as pilot:
        view = screen(pilot)
        await eventually(pilot, lambda: shown_title(view.preview_pane) == "The [b]Unknown")
        assert shown_title(view.chapters_list) == "1 · [Draft] Notes"
        await pilot.press("enter", "d")
        await pilot.pause()
        assert isinstance(pilot.app.screen, Confirm)
        await pilot.press("y")
        await pilot.pause()
        assert any("The [b]Unknown" in str(n.message) for n in pilot.app._notifications)
