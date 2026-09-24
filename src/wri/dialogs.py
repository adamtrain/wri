"""Pop-up dialogs: asking for a title, confirming a delete, choosing a section, help."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from wri.book import BookError, Section


class TextPrompt(ModalScreen[str | None]):
    """Ask for one line of text, such as a title.

    ``check`` tidies the answer or raises BookError to reject it, and ``describe``
    turns a tidied answer into a line shown under the input as the writer types.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        heading: str,
        value: str = "",
        *,
        placeholder: str = "",
        note: str = "",
        check: Callable[[str], str] | None = None,
        describe: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__()
        self.heading = heading
        self.value = value
        self.placeholder = placeholder
        self.note = note
        self.check = check
        self.describe = describe

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = Content(self.heading)
            if self.note:
                yield Static(self.note, classes="note", markup=False)
            yield Input(self.value, placeholder=self.placeholder)
            yield Static(classes="description", markup=False)
            yield Static(classes="error", markup=False)
            yield Static("[b]enter[/b] save   [b]esc[/b] cancel", classes="keys")

    def on_mount(self) -> None:
        self.show_description(self.value)

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        try:
            value = self.check(event.value) if self.check else event.value
        except BookError as error:
            self.query_one(".error", Static).update(str(error))
            return
        self.dismiss(value)

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self.query_one(".error", Static).update("")
        self.show_description(event.value)

    def show_description(self, value: str) -> None:
        if self.describe is None:
            return
        try:
            text = self.describe(self.check(value) if self.check else value)
        except BookError:
            text = ""
        self.query_one(".description", Static).update(text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Confirm(ModalScreen[bool]):
    """Ask before doing something drastic."""

    BINDINGS = [
        Binding("y", "choose(True)", "Yes"),
        Binding("n,escape", "choose(False)", "No"),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
    ]

    def __init__(self, heading: str, message: str, action: str) -> None:
        super().__init__()
        self.heading = heading
        self.message = message
        self.action = action

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = Content(self.heading)
            yield Static(self.message, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.action, id="confirm", variant="error")
            yield Static(f"[b]y[/b] {self.action.lower()}   [b]n[/b] cancel", classes="keys")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_choose(self, choice: bool) -> None:
        self.dismiss(choice)


class SectionPicker(ModalScreen[int | None]):
    """Choose a section to move a chapter into."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("j", "cursor(1)", show=False),
        Binding("k", "cursor(-1)", show=False),
    ]

    def __init__(self, heading: str, sections: list[Section], current: int) -> None:
        super().__init__()
        self.heading = heading
        self.sections = sections
        self.current = current

    def compose(self) -> ComposeResult:
        options = []
        for index, section in enumerate(self.sections):
            label = Text.assemble((f"{index + 1:>2}  ", "dim"), section.label)
            if index == self.current:
                label.append("  (here now)", style="italic")
            options.append(Option(label, disabled=index == self.current))
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = Content(self.heading)
            yield OptionList(*options)
            yield Static("[b]enter[/b] move here   [b]esc[/b] cancel", classes="keys")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.highlighted = next(
            (index for index in range(len(self.sections)) if index != self.current), None
        )

    @on(OptionList.OptionSelected)
    def chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def action_cursor(self, step: int) -> None:
        options = self.query_one(OptionList)
        if step > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """The keys, and a short note on how the book is stored."""

    BINDINGS = [Binding("escape,q,question_mark", "close", "Close")]

    def __init__(self, groups: list[tuple[str, list[tuple[str, str]]]], notes: list[str]) -> None:
        super().__init__()
        self.groups = groups
        self.notes = notes

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog help") as dialog:
            dialog.border_title = "Keys"
            dialog.border_subtitle = "esc to close"
            for heading, keys in self.groups:
                yield Static(heading, classes="heading")
                for key, meaning in keys:
                    with Horizontal(classes="key-row"):
                        yield Static(key, classes="key", markup=False)
                        yield Static(meaning, classes="meaning", markup=False)
            for note in self.notes:
                yield Static(note, classes="about", markup=False)

    def action_close(self) -> None:
        self.dismiss(None)
