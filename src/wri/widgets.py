"""Widgets for the book screen."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from wri.book import Book
from wri.text import plural

MOVE = Binding.Group("Move", compact=True)


def words_label(words: int) -> str:
    return f"{words:,}" if words else "—"


def row(number: int, title: str, words: int, number_width: int) -> Option:
    """A list entry: the item's number, its title and its word count, spread across the row."""
    grid = Table.grid(expand=True, padding=(0, 1, 0, 0))
    grid.add_column(width=number_width, justify="right", style="dim")
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True, style="dim")
    grid.add_row(str(number), Text(title), words_label(words))
    return Option(grid)


def hint(text: str) -> Option:
    """A greyed-out entry for an empty list."""
    return Option(Text(text, style="italic"), disabled=True)


class BookList(OptionList):
    """A list of sections or chapters.

    Adds vim-style movement, and opens an item on enter or double-click rather
    than on every click.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
    ]

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        index = event.style.meta.get("option")
        if index is None or self.options[index].disabled:
            return
        self.highlighted = index
        if event.chain > 1:
            self.action_select()


class SectionList(BookList):
    BINDINGS = [
        Binding("n", "screen.new_section", "New"),
        Binding("r", "screen.rename_section", "Rename"),
        Binding("d", "screen.delete_section", "Delete"),
        Binding("shift+up", "screen.move_section(-1)", "Move up", key_display="⇧↑", group=MOVE),
        Binding("shift+down", "screen.move_section(1)", "Move down", key_display="⇧↓", group=MOVE),
        Binding("enter", "select", "Open"),
        Binding("a", "screen.new_section", "New", show=False),
        Binding("f2", "screen.rename_section", "Rename", show=False),
        Binding("delete", "screen.delete_section", "Delete", show=False),
        Binding("K", "screen.move_section(-1)", "Move up", show=False),
        Binding("J", "screen.move_section(1)", "Move down", show=False),
        Binding("right,l", "screen.focus_chapters", "Chapters", show=False),
    ]


class ChapterList(BookList):
    BINDINGS = [
        Binding("n", "screen.new_chapter", "New"),
        Binding("r", "screen.rename_chapter", "Rename"),
        Binding("d", "screen.delete_chapter", "Delete"),
        Binding("shift+up", "screen.move_chapter(-1)", "Move up", key_display="⇧↑", group=MOVE),
        Binding("shift+down", "screen.move_chapter(1)", "Move down", key_display="⇧↓", group=MOVE),
        Binding("m", "screen.move_chapter_to_section", "Move to…"),
        Binding("enter", "select", "Edit"),
        Binding("a", "screen.new_chapter", "New", show=False),
        Binding("e", "select", "Edit", show=False),
        Binding("f2", "screen.rename_chapter", "Rename", show=False),
        Binding("delete", "screen.delete_chapter", "Delete", show=False),
        Binding("K", "screen.move_chapter(-1)", "Move up", show=False),
        Binding("J", "screen.move_chapter(1)", "Move down", show=False),
        Binding("left,h,escape", "screen.focus_sections", "Sections", show=False),
    ]


class TopBar(Horizontal):
    """The book's title on the left; how much of it there is on the right."""

    def compose(self) -> ComposeResult:
        yield Static(id="book-title")
        yield Static(id="book-counts")
        yield Static(id="book-words")

    def show(self, book: Book) -> None:
        settings = book.settings
        title = Content.from_markup("[b]$title[/b]", title=settings.title)
        if settings.author:
            title += Content.from_markup("  [$text-muted]by $author", author=settings.author)
        self.query_one("#book-title", Static).update(title)

        counts = Content.from_markup(
            "[$text-muted]$sections · $chapters · ",
            sections=plural(len(book.sections), "section"),
            chapters=plural(book.chapter_count, "chapter"),
        )
        self.query_one("#book-counts", Static).update(counts)

        words = book.total_words()
        progress = Content.from_markup("[b]$words[/b]", words=plural(words, "word"))
        if settings.target:
            progress += Content("  ") + progress_bar(words / settings.target)
            progress += Content.from_markup(
                " [$text-muted]of $target", target=f"{settings.target:,}"
            )
        self.query_one("#book-words", Static).update(progress)


def progress_bar(fraction: float, width: int = 16) -> Content:
    """A thin progress bar with the percentage after it."""
    filled = round(min(fraction, 1.0) * width)
    return Content.assemble(
        ("━" * filled, "$accent"),
        ("━" * (width - filled), "$foreground 20%"),
        (f" {fraction:.0%}", "bold"),
    )
