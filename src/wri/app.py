"""The wri text user interface."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from textual import getters, on
from textual.app import App, ComposeResult, SuspendNotSupported, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import Footer, Markdown, OptionList

from wri.book import (
    CONFIG_FILE,
    TRASH_DIR,
    Book,
    BookError,
    Chapter,
    Section,
    clean_title,
    format_name,
)
from wri.compile import write_manuscript
from wri.dialogs import Confirm, HelpScreen, SectionPicker, TextPrompt
from wri.editor import COMMAND_NOT_FOUND, editor_command, run_editor
from wri.text import body, plural, read_markdown, without_title
from wri.widgets import ChapterList, SectionList, TopBar, hint, row

DEFAULT_THEME = "flexoki"
READING_SPEED = 240  # words per minute, for "5 min read"
# The preview shows about this many characters of a chapter, which keeps it quick
# while you move through the list. Tab into the preview to read the whole thing.
PREVIEW_LIMIT = 6_000
PREVIEW_DELAY = 0.1  # seconds to wait for the highlight to settle before previewing
POLL_SECONDS = 1.5

WELCOME = """\
# Welcome to wri

Your book lives in plain folders and Markdown files: each **section** is a
folder, and each **chapter** is a Markdown file inside it. wri keeps them
numbered in order, and your editor does the writing.

Press **n** to add your first section.
"""

NO_CHAPTERS_OUTSIDE = """\
*No chapters here yet.*

Press **enter** to step into this section, then **n** to start its first chapter.
"""

NO_CHAPTERS_INSIDE = "*No chapters here yet.* Press **n** to start the first one."

EMPTY_CHAPTER = "*This chapter is empty.* Press **enter** to start writing."

KEYS = [
    (
        "Sections",
        [
            ("enter  →", "Go into the section"),
            ("n", "New section after this one"),
            ("r", "Rename"),
            ("d", "Delete (it goes to the book's .trash folder)"),
            ("⇧↑ ⇧↓  K J", "Move up or down"),
        ],
    ),
    (
        "Chapters",
        [
            ("enter  e", "Write: open the chapter in your editor"),
            ("n", "New chapter after this one"),
            ("r", "Rename"),
            ("d", "Delete (it goes to the book's .trash folder)"),
            ("⇧↑ ⇧↓  K J", "Move up or down"),
            ("m", "Move to another section"),
            ("esc  ←", "Back to the sections"),
        ],
    ),
    (
        "Anywhere",
        [
            ("c", "Compile the book into one Markdown file"),
            ("s", f"Book settings: edit {CONFIG_FILE}"),
            ("p", "Show or hide the preview"),
            ("ctrl+p", "Command palette, including themes"),
            ("q", "Quit"),
        ],
    ),
]

ABOUT = (
    "Sections are the numbered folders in your book's folder, and chapters are the "
    "numbered Markdown files inside them. wri renumbers them as you add, move and "
    "delete, and notices changes made elsewhere. Anything without a number at the "
    "front of its name is ignored, so notes and images can live alongside."
)


class WriApp(App[None]):
    """wri: outline and write a book in folders of Markdown files."""

    CSS_PATH = "wri.tcss"
    TITLE = "wri"

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.book = Book(root)
        preferred = load_preferences().get("theme")
        valid = isinstance(preferred, str) and preferred in self.available_themes
        self.theme = preferred if valid else DEFAULT_THEME

    def get_default_screen(self) -> Screen:
        return BookScreen(self.book)

    def on_mount(self) -> None:
        self.theme_changed_signal.subscribe(self, self._remember_theme)

    def _remember_theme(self, theme: Theme) -> None:
        save_preference("theme", theme.name)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        if isinstance(screen, BookScreen):
            commands: list[tuple[str, str, Callable[[], object]]] = [
                ("Compile", "Stitch the book into one Markdown file", screen.action_compile),
                ("Book settings", f"Edit {CONFIG_FILE}", screen.action_settings),
                ("Toggle preview", "Show or hide the preview", screen.action_toggle_preview),
                ("Reload", "Re-read the book from disk", screen.action_reload),
                ("Help", "Keys, and how wri stores your book", screen.action_help),
            ]
            for title, help, callback in commands:
                yield SystemCommand(title, help, callback)
        yield from super().get_system_commands(screen)

    def edit(self, path: Path) -> None:
        """Suspend the TUI and open ``path`` in the writer's editor until it closes."""
        found = editor_command()
        if found is None:
            self.notify("Set $EDITOR to your editor, e.g. export EDITOR=nano", severity="error")
            return
        command, _ = found
        try:
            with self.suspend():
                status = run_editor(command, path)
        except SuspendNotSupported:
            self.notify("Can't open an editor from here.", severity="error")
            return
        if status == COMMAND_NOT_FOUND:
            self.notify(f"Couldn't run “{command}”. Check $EDITOR.", severity="error", markup=False)


class BookScreen(Screen[None]):
    """The whole book at a glance: sections, the chapters of the highlighted section, a preview."""

    BINDINGS = [
        Binding("c", "compile", "Compile"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("q", "app.quit", "Quit"),
        Binding("p", "toggle_preview", "Preview", show=False),
        Binding("s", "settings", "Settings", show=False),
        Binding("ctrl+r", "reload", "Reload", show=False),
    ]
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (96, "-wide")]
    AUTO_FOCUS = "#sections"

    app = getters.app(WriApp)
    sections_list = getters.query_one("#sections", SectionList)
    chapters_list = getters.query_one("#chapters", ChapterList)
    preview = getters.query_one("#preview", Markdown)
    preview_pane = getters.query_one("#preview-pane", VerticalScroll)

    def __init__(self, book: Book) -> None:
        super().__init__()
        self.book = book
        self._fingerprint: tuple[object, ...] = ()
        self._chapter_memory: dict[Path, int] = {}
        self._preview_timer: Timer | None = None
        self._preview_key: object = None
        self._reported_settings_error: str | None = None

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with Horizontal(id="columns"):
            yield SectionList(id="sections", classes="column")
            yield ChapterList(id="chapters", classes="column")
            with VerticalScroll(id="preview-pane", classes="column"):
                yield Markdown(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.preview_pane.can_focus = True
        self.redraw(section_index=0)
        self.set_interval(POLL_SECONDS, self.check_disk)

    # What's highlighted

    @property
    def section_index(self) -> int | None:
        index = self.sections_list.highlighted
        return index if self.book.sections and index is not None else None

    @property
    def section(self) -> Section | None:
        index = self.section_index
        return None if index is None else self.book.sections[index]

    @property
    def chapter_index(self) -> int | None:
        section = self.section
        index = self.chapters_list.highlighted
        return index if section and section.chapters and index is not None else None

    @property
    def chapter(self) -> Chapter | None:
        section, index = self.section, self.chapter_index
        return None if section is None or index is None else section.chapters[index]

    # Drawing

    def redraw(self, section_index: int | None = None, chapter_index: int | None = None) -> None:
        """Redraw everything from the book, highlighting the given positions if any."""
        self.app.title = self.book.settings.title
        self.query_one(TopBar).show(self.book)
        self.fill_sections(section_index)
        self.fill_chapters(chapter_index)
        self.schedule_preview()
        self._fingerprint = self.book.fingerprint()
        self.report_settings_error()

    def fill_sections(self, index: int | None = None) -> None:
        sections = self.book.sections
        listing = self.sections_list
        index = listing.highlighted if index is None else index
        width = len(str(len(sections)))
        options = [
            row(number, section.label, self.book.section_words(section), width)
            for number, section in enumerate(sections, 1)
        ] or [hint("No sections yet")]
        with self.prevent(OptionList.OptionHighlighted):
            listing.set_options(options)
            listing.highlighted = min(index or 0, len(sections) - 1) if sections else None
        listing.border_title = "Sections"
        listing.border_subtitle = plural(len(sections), "section") if sections else ""

    def fill_chapters(self, index: int | None = None) -> None:
        section = self.section
        listing = self.chapters_list
        chapters = section.chapters if section else ()
        if index is None and section:
            index = self._chapter_memory.get(section.path, 0)
        width = len(str(len(chapters)))
        options = [
            row(number, chapter.label, self.book.words(chapter), width)
            for number, chapter in enumerate(chapters, 1)
        ] or [hint("No chapters yet" if section else "")]
        with self.prevent(OptionList.OptionHighlighted):
            listing.set_options(options)
            listing.highlighted = min(index or 0, len(chapters) - 1) if chapters else None
        if section and self.section_index is not None:
            listing.border_title = Content(f"{self.section_index + 1} · {section.label}")
            listing.border_subtitle = plural(len(chapters), "chapter") if chapters else ""
        else:
            listing.border_title = "Chapters"
            listing.border_subtitle = ""
        self.remember_chapter()

    def remember_chapter(self) -> None:
        if (section := self.section) and (index := self.chapter_index) is not None:
            self._chapter_memory[section.path] = index

    def schedule_preview(self) -> None:
        """Update the preview shortly, so scrolling quickly through the list stays smooth."""
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(PREVIEW_DELAY, self.show_preview)

    def show_preview(self) -> None:
        pane = self.preview_pane
        chapter = self.chapter
        if chapter is not None:
            words = self.book.words(chapter)
            pane.border_title = Content(chapter.label)
            minutes = max(1, round(words / READING_SPEED))
            pane.border_subtitle = f"{plural(words, 'word')} · {minutes} min read" if words else ""
            text = without_title(body(read_markdown(chapter.path)), chapter.title).strip()
            if self.focused is not pane:
                text = _shorten(text)
            text = text or EMPTY_CHAPTER
            key: object = (chapter.path, text)
        else:
            inside = self.focused is self.chapters_list
            if self.section:
                text = NO_CHAPTERS_INSIDE if inside else NO_CHAPTERS_OUTSIDE
                pane.border_title = Content(self.section.label)
            else:
                text = WELCOME
                pane.border_title = Content(self.book.settings.title)
            key = text
            pane.border_subtitle = ""
        if key != self._preview_key:
            self._preview_key = key
            self.preview.update(text)
            pane.scroll_home(animate=False)

    def report_settings_error(self) -> None:
        error = self.book.settings_error
        if error and error != self._reported_settings_error:
            self.notify(
                error, title=f"Problem in {CONFIG_FILE}", severity="error", timeout=8, markup=False
            )
        self._reported_settings_error = error

    # Keeping up with the disk

    def check_disk(self) -> None:
        if self.book.fingerprint() != self._fingerprint:
            self.reload_book()

    def reload_book(self) -> None:
        """Re-read the book, keeping the same section and chapter highlighted if they exist."""
        section, chapter = self.section, self.chapter
        section_index, chapter_index = self.section_index, self.chapter_index
        self.book.reload()
        if section is not None:
            section_index = self._find_section(section.path, fallback=section_index)
            if chapter is not None and section_index is not None:
                chapters = self.book.sections[section_index].chapters
                paths = [item.path for item in chapters]
                if chapter.path in paths:
                    chapter_index = paths.index(chapter.path)
        self.redraw(section_index, chapter_index)

    def _find_section(self, path: Path, fallback: int | None = None) -> int | None:
        for index, section in enumerate(self.book.sections):
            if section.path == path:
                return index
        return fallback

    def _find_chapter(self, section_path: Path, chapter_path: Path) -> tuple[int, int]:
        """Where a chapter is now, or a BookError if it has moved or gone."""
        section_index = self._find_section(section_path)
        if section_index is not None:
            chapters = self.book.sections[section_index].chapters
            for index, chapter in enumerate(chapters):
                if chapter.path == chapter_path:
                    return section_index, index
        raise BookError(f"“{chapter_path.stem}” changed on disk while you were busy. Try again.")

    @staticmethod
    def _disk_name(index: int, title: str, count: int) -> str:
        """The name an item will have on disk at ``index`` in a list of ``count`` items."""
        return format_name(index + 1, title, max(2, len(str(count))))

    @contextmanager
    def reporting(self) -> Iterator[None]:
        """Show any BookError as a notification and resync with the disk."""
        try:
            yield
        except BookError as error:
            self.notify(str(error), title="Couldn't do that", severity="error", markup=False)
            self.reload_book()

    # Moving around

    @on(OptionList.OptionHighlighted, "#sections")
    def section_highlighted(self) -> None:
        self.fill_chapters()
        self.schedule_preview()

    @on(OptionList.OptionSelected, "#sections")
    def section_selected(self) -> None:
        self.chapters_list.focus()

    @on(OptionList.OptionHighlighted, "#chapters")
    def chapter_highlighted(self) -> None:
        self.remember_chapter()
        self.schedule_preview()

    @on(OptionList.OptionSelected, "#chapters")
    def chapter_selected(self) -> None:
        self.action_edit_chapter()

    def on_descendant_focus(self) -> None:
        self.schedule_preview()

    def action_focus_chapters(self) -> None:
        self.chapters_list.focus()

    def action_focus_sections(self) -> None:
        self.sections_list.focus()

    # Sections

    def action_new_section(self) -> None:
        index = 0 if self.section_index is None else self.section_index + 1

        def create(title: str | None) -> None:
            if title is not None:
                with self.reporting():
                    self.redraw(self.book.add_section(title, index))

        self.app.push_screen(
            TextPrompt(
                "New section",
                placeholder="Section title",
                check=clean_title,
                describe=lambda title: (
                    f"→ {self._disk_name(index, title, len(self.book.sections) + 1)}/"
                ),
            ),
            create,
        )

    def action_rename_section(self) -> None:
        if (section := self.section) is None:
            return

        def rename(title: str | None) -> None:
            if title is None or title == section.title:
                return
            with self.reporting():
                index = self._find_section(section.path)
                if index is None:
                    raise BookError(f"“{section.label}” changed on disk. Try again.")
                self.book.rename_section(index, title)
                self.redraw(index)

        position, count = self.book.sections.index(section), len(self.book.sections)
        self.app.push_screen(
            TextPrompt(
                "Rename section",
                section.title,
                check=clean_title,
                describe=lambda title: f"→ {self._disk_name(position, title, count)}/",
            ),
            rename,
        )

    def action_delete_section(self) -> None:
        if (section := self.section) is None:
            return
        count = len(section.chapters)
        words = self.book.section_words(section)
        detail = f"It has {plural(count, 'chapter')} and {plural(words, 'word')}. " if count else ""
        message = f"{detail}It will be moved to the {TRASH_DIR} folder inside your book."

        def delete(confirmed: bool | None) -> None:
            if not confirmed:
                return
            with self.reporting():
                index = self._find_section(section.path)
                if index is None:
                    raise BookError(f"“{section.label}” changed on disk. Try again.")
                self.book.delete_section(index)
                self.notify(
                    f"Moved “{section.label}” to {TRASH_DIR}", title="Deleted", markup=False
                )
                self.redraw(max(0, index - 1) if index >= len(self.book.sections) else index)

        self.app.push_screen(Confirm(f"Delete “{section.label}”?", message, "Delete"), delete)

    def action_move_section(self, step: int) -> None:
        if (index := self.section_index) is None:
            return
        with self.reporting():
            self.redraw(self.book.move_section(index, index + step))

    # Chapters

    def action_new_chapter(self) -> None:
        if (section := self.section) is None:
            self.notify("Add a section first: press n in the sections column.")
            return
        index = len(section.chapters) if self.chapter_index is None else self.chapter_index + 1

        def create(title: str | None) -> None:
            if title is None:
                return
            with self.reporting():
                section_index = self._find_section(section.path)
                if section_index is None:
                    raise BookError(f"“{section.label}” changed on disk. Try again.")
                chapter_index = self.book.add_chapter(section_index, title, index)
                self.redraw(section_index, chapter_index)
                self.chapters_list.focus()
                self.edit(self.book.sections[section_index].chapters[chapter_index].path)

        count = len(section.chapters) + 1
        self.app.push_screen(
            TextPrompt(
                "New chapter",
                placeholder="Chapter title",
                note=f"Section {self.book.sections.index(section) + 1} · {section.label}",
                check=clean_title,
                describe=lambda title: f"→ {self._disk_name(index, title, count)}.md",
            ),
            create,
        )

    def action_edit_chapter(self) -> None:
        if (chapter := self.chapter) is not None:
            self.edit(chapter.path)

    def action_rename_chapter(self) -> None:
        if (section := self.section) is None or (chapter := self.chapter) is None:
            return

        def rename(title: str | None) -> None:
            if title is None or title == chapter.title:
                return
            with self.reporting():
                section_index, index = self._find_chapter(section.path, chapter.path)
                self.book.rename_chapter(section_index, index, title)
                self.redraw(section_index, index)

        position, count = section.chapters.index(chapter), len(section.chapters)
        suffix = chapter.path.suffix
        self.app.push_screen(
            TextPrompt(
                "Rename chapter",
                chapter.title,
                check=clean_title,
                describe=lambda title: f"→ {self._disk_name(position, title, count)}{suffix}",
            ),
            rename,
        )

    def action_delete_chapter(self) -> None:
        if (section := self.section) is None or (chapter := self.chapter) is None:
            return
        words = self.book.words(chapter)
        detail = f"It has {plural(words, 'word')}. " if words else ""
        message = f"{detail}It will be moved to the {TRASH_DIR} folder inside your book."

        def delete(confirmed: bool | None) -> None:
            if not confirmed:
                return
            with self.reporting():
                section_index, index = self._find_chapter(section.path, chapter.path)
                self.book.delete_chapter(section_index, index)
                self.notify(
                    f"Moved “{chapter.label}” to {TRASH_DIR}", title="Deleted", markup=False
                )
                remaining = len(self.book.sections[section_index].chapters)
                self.redraw(section_index, min(index, remaining - 1) if remaining else None)

        self.app.push_screen(Confirm(f"Delete “{chapter.label}”?", message, "Delete"), delete)

    def action_move_chapter(self, step: int) -> None:
        if (section_index := self.section_index) is None or (index := self.chapter_index) is None:
            return
        with self.reporting():
            self.redraw(section_index, self.book.move_chapter(section_index, index, index + step))

    def action_move_chapter_to_section(self) -> None:
        if (section := self.section) is None or (chapter := self.chapter) is None:
            return
        if len(self.book.sections) < 2:
            self.notify("There's no other section to move it to yet.")
            return
        choices = list(self.book.sections)

        def move(choice: int | None) -> None:
            if choice is None:
                return
            destination = choices[choice]
            with self.reporting():
                section_index, index = self._find_chapter(section.path, chapter.path)
                target = self._find_section(destination.path)
                if target is None:
                    raise BookError(f"“{destination.label}” changed on disk. Try again.")
                new_index = self.book.move_chapter_to_section(section_index, index, target)
                self.redraw(target, new_index)
                self.notify(f"Moved “{chapter.label}” to “{destination.label}”", markup=False)

        picker = SectionPicker(f"Move “{chapter.label}” to…", choices, choices.index(section))
        self.app.push_screen(picker, move)

    # Everything else

    def action_compile(self) -> None:
        with self.reporting():
            result = write_manuscript(self.book)
            try:
                where = result.path.relative_to(self.book.root)
            except ValueError:
                where = result.path
            self.notify(
                f"{plural(result.chapters, 'chapter')}, {plural(result.words, 'word')} → {where}",
                title="Compiled",
                markup=False,
            )

    def action_settings(self) -> None:
        path = self.book.root / CONFIG_FILE
        if not path.exists():
            Book.create(self.book.root)
        self.edit(path)

    def action_toggle_preview(self) -> None:
        if self.focused is self.preview_pane:
            self.chapters_list.focus()
        self.toggle_class("-no-preview")

    def action_reload(self) -> None:
        self.reload_book()
        self.notify("Reloaded from disk.")

    def action_help(self) -> None:
        found = editor_command()
        if found is None:
            editor = "No editor found. Set $EDITOR, for example: export EDITOR=nano"
        else:
            command, source = found
            editor = f"Chapters open in {command} (from {source})."
            if source == "PATH":
                editor += " Set $EDITOR to choose a different editor."
        self.app.push_screen(HelpScreen(KEYS, [ABOUT, editor]))

    def edit(self, path: Path) -> None:
        """Open ``path`` in the writer's editor, then catch up with whatever changed."""
        self.app.edit(path)
        self.reload_book()


def _shorten(text: str) -> str:
    """The start of a long chapter, cut at a paragraph break, so the preview stays quick."""
    if len(text) <= PREVIEW_LIMIT:
        return text
    cut = text.find("\n\n", PREVIEW_LIMIT)
    if cut == -1:
        cut = text.find("\n", PREVIEW_LIMIT)
    if cut == -1:
        cut = PREVIEW_LIMIT
    return text[:cut] + "\n\n*…continues. Press **tab** to read the rest here.*"


def _preferences_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "wri" / "preferences.json"


def load_preferences() -> dict[str, object]:
    try:
        preferences = json.loads(_preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return preferences if isinstance(preferences, dict) else {}


def save_preference(key: str, value: object) -> None:
    preferences = load_preferences()
    if preferences.get(key) == value:
        return
    preferences[key] = value
    path = _preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(preferences, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
