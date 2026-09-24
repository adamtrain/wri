from pathlib import Path

import pytest

from wri.book import (
    CONFIG_FILE,
    TRASH_DIR,
    Book,
    BookError,
    clean_title,
    format_name,
    parse_name,
)

from conftest import make_book, names


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("03 The Middle", (3, "The Middle")),
        ("3-the-middle", (3, "the-middle")),
        ("03. The Middle", (3, "The Middle")),
        ("03_notes", (3, "notes")),
        ("12", (12, "")),
        ("03 ...And Then", (3, "...And Then")),
        ("01 1984 Revisited", (1, "1984 Revisited")),
        ("notes", None),
        ("Chapter 3", None),
    ],
)
def test_parse_name(name: str, expected: tuple[int, str] | None) -> None:
    assert parse_name(name) == expected


def test_format_name() -> None:
    assert format_name(3, "The Middle") == "03 The Middle"
    assert format_name(3, "") == "03"
    assert format_name(7, "Seven", width=3) == "007 Seven"


def test_clean_title() -> None:
    assert clean_title("  Why   We Sleep ") == "Why We Sleep"
    assert clean_title("Part One: Beginnings?") == "Part One: Beginnings?"
    for bad in ["", "   ", "Before/After", "tab\x07bell", "x" * 300]:
        with pytest.raises(BookError):
            clean_title(bad)


def test_create_writes_settings(tmp_path: Path) -> None:
    book = Book.create(tmp_path / "Night Book")
    assert book.settings.title == "Night Book"
    assert (tmp_path / "Night Book" / CONFIG_FILE).is_file()
    assert book.sections == []


def test_find_walks_up_from_a_section(book: Book) -> None:
    book.add_section("Intro")
    assert Book.find(book.sections[0].path) == book.root
    assert Book.find(book.root.parent) is None
    assert Book.find(book.root / "missing") is None


def test_add_sections_in_order(book: Book) -> None:
    book.add_section("Beginning")
    book.add_section("End")
    assert book.add_section("Middle", 1) == 1
    assert names(book.root) == ["01 Beginning", "02 Middle", "03 End", CONFIG_FILE]
    assert [section.title for section in book.sections] == ["Beginning", "Middle", "End"]


def test_rename_section_keeps_its_chapters(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"Intro": {"Hello": "hi"}})
    book.rename_section(0, "Introduction")
    assert names(book.root) == ["01 Introduction", CONFIG_FILE]
    assert (book.root / "01 Introduction" / "01 Hello.md").read_text() == "hi"


def test_rename_only_changing_case(book: Book) -> None:
    book.add_section("intro")
    book.rename_section(0, "Intro")
    assert names(book.root) == ["01 Intro", CONFIG_FILE]


def test_move_section_swaps_numbers_and_contents(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a": "first"}, "B": {"b": "second"}})
    assert book.move_section(0, 1) == 1
    assert names(book.root) == ["01 B", "02 A", CONFIG_FILE]
    assert (book.root / "02 A" / "01 a.md").read_text() == "first"
    assert book.move_section(1, 5) == 1  # already last: nothing to do


def test_delete_section_goes_to_trash(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a": "keep me"}, "B": {}, "C": {}})
    trashed = book.delete_section(0)
    assert names(book.root) == ["01 B", "02 C", CONFIG_FILE]
    assert trashed.parent.parent == book.root / TRASH_DIR
    assert (trashed / "01 a.md").read_text() == "keep me"
    assert [section.title for section in book.sections] == ["B", "C"]


def test_chapters_add_move_rename(book: Book) -> None:
    book.add_section("Part")
    book.add_chapter(0, "Two")
    book.add_chapter(0, "Three")
    assert book.add_chapter(0, "One", 0) == 0
    folder = book.sections[0].path
    assert names(folder) == ["01 One.md", "02 Two.md", "03 Three.md"]
    assert (folder / "01 One.md").read_text() == ""

    (folder / "03 Three.md").write_text("three")
    assert book.move_chapter(0, 2, 0) == 0
    assert names(folder) == ["01 Three.md", "02 One.md", "03 Two.md"]
    assert (folder / "01 Three.md").read_text() == "three"

    book.rename_chapter(0, 1, "Uno")
    assert names(folder) == ["01 Three.md", "02 Uno.md", "03 Two.md"]


def test_move_chapter_to_another_section(tmp_path: Path) -> None:
    book = make_book(
        tmp_path / "book",
        {"A": {"a1": "one", "a2": "two", "a3": "three"}, "B": {"b1": ""}},
    )
    assert book.move_chapter_to_section(0, 1, 1) == 1
    assert names(book.root / "01 A") == ["01 a1.md", "02 a3.md"]
    assert names(book.root / "02 B") == ["01 b1.md", "02 a2.md"]
    assert (book.root / "02 B" / "02 a2.md").read_text() == "two"
    assert book.move_chapter_to_section(0, 0, 0) == 0  # same section: nothing to do


def test_delete_chapter_goes_to_trash(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "one", "a2": "two"}})
    trashed = book.delete_chapter(0, 0)
    assert names(book.root / "01 A") == ["01 a2.md"]
    assert trashed.read_text() == "one"
    assert trashed.parent.name == "01 A"
    assert trashed.is_relative_to(book.root / TRASH_DIR)


def test_other_files_are_left_alone(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "", "a2": ""}})
    section = book.root / "01 A"
    (section / "notes.md").write_text("not a chapter")
    (section / "03 figure.png").write_text("not markdown")
    (section / ".draft.md").write_text("hidden")
    (book.root / "images").mkdir()
    (book.root / "README.md").write_text("readme")
    book.reload()
    assert [chapter.title for chapter in book.sections[0].chapters] == ["a1", "a2"]
    assert [section.title for section in book.sections] == ["A"]

    book.move_chapter(0, 0, 1)
    assert names(section) == ["01 a2.md", "02 a1.md", "03 figure.png", "notes.md"]
    assert (section / ".draft.md").exists()
    assert names(book.root) == ["01 A", "README.md", "images", CONFIG_FILE]


def test_loose_names_are_tidied_by_the_next_change(book: Book) -> None:
    folder = book.root / "5-drafts"
    folder.mkdir()
    (folder / "2.second.md").write_text("")
    (folder / "1_first.MD").write_text("")
    (folder / "10 tenth.markdown").write_text("")
    book.reload()
    assert [chapter.title for chapter in book.sections[0].chapters] == ["first", "second", "tenth"]
    book.rename_section(0, "Drafts")
    assert names(book.root / "01 Drafts") == ["10 tenth.markdown", "1_first.MD", "2.second.md"]
    book.rename_chapter(0, 0, "first")
    assert names(book.root / "01 Drafts") == ["01 first.MD", "02 second.md", "03 tenth.markdown"]


def test_numbers_widen_past_99(book: Book) -> None:
    folder = book.root / "01 Long"
    folder.mkdir()
    for number in range(1, 101):
        (folder / f"{number} chapter {number}.md").write_text("")
    book.reload()
    book.move_chapter(0, 0, 1)
    listing = names(folder)
    assert listing[0] == "001 chapter 2.md"
    assert listing[1] == "002 chapter 1.md"
    assert listing[-1] == "100 chapter 100.md"


def test_refuses_to_clobber_something_else(book: Book) -> None:
    book.add_section("Alpha")
    book.add_section("Beta")
    (book.root / "01 Beta").write_text("a file, not a section")
    with pytest.raises(BookError, match="already has it"):
        book.move_section(1, 0)
    assert names(book.root) == ["01 Alpha", "01 Beta", "02 Beta", CONFIG_FILE]


def test_recovers_from_an_interrupted_rename(book: Book) -> None:
    (book.root / ".wri-abc123-02 Middle").mkdir()
    (book.root / "01 Start").mkdir()
    (book.root / "01 Start" / ".wri-0f0f0f-01 Hello.md").write_text("safe")
    book = Book(book.root)
    assert [section.title for section in book.sections] == ["Start", "Middle"]
    assert (book.root / "01 Start" / "01 Hello.md").read_text() == "safe"


def test_settings(book: Book) -> None:
    (book.root / CONFIG_FILE).write_text(
        'title = "Sleep"\nauthor = "A. Writer"\ntarget = 50000\n'
        '[compile]\nchapter_heading = "Chapter {number}: {title}"\n'
    )
    book.reload()
    assert book.settings.title == "Sleep"
    assert book.settings.author == "A. Writer"
    assert book.settings.target == 50000
    assert book.settings.chapter_heading == "Chapter {number}: {title}"
    assert book.settings_error is None


@pytest.mark.parametrize(
    "text",
    ["title = ", "target = 'lots'", "target = -5", "title = 3", "compile = 'yes'"],
)
def test_bad_settings_keep_the_last_good_ones(book: Book, text: str) -> None:
    (book.root / CONFIG_FILE).write_text('title = "Good"\n')
    book.reload()
    (book.root / CONFIG_FILE).write_text(text)
    book.reload()
    assert book.settings_error
    assert book.settings.title == "Good"


def test_words_are_counted_and_cached(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "one two three", "a2": "four five"}})
    assert book.total_words() == 5
    assert book.section_words(book.sections[0]) == 5
    chapter = book.sections[0].chapters[0]
    chapter.path.write_text("just two")
    assert book.words(chapter) == 2


def test_fingerprint_notices_outside_changes(tmp_path: Path) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "text"}})
    before = book.fingerprint()
    (book.root / "01 A" / "01 a1.md").write_text("more text than before")
    assert book.fingerprint() != before
    before = book.fingerprint()
    (book.root / "02 B").mkdir()
    assert book.fingerprint() != before
