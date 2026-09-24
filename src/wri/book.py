"""A book on disk.

A book is a folder with a ``wri.toml`` file in it. The book's *sections* are the
numbered folders inside it, and each section's *chapters* are the numbered
Markdown files inside that folder::

    My Book/
        wri.toml
        01 Introduction/
            01 Why This Book.md
            02 How to Read It.md
        02 The Argument/
            01 First Principles.md

The number at the front of a name is the item's position. Whenever wri changes
the structure it renames things so the numbers run 01, 02, 03… in order.
Anything without a leading number, and anything hidden, is left alone.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from wri.text import count_words, read_markdown

CONFIG_FILE = "wri.toml"
TRASH_DIR = ".trash"
CHAPTER_SUFFIXES = (".md", ".markdown")
MAX_TITLE_BYTES = 200

_CANONICAL_NAME = re.compile(r"([0-9]+) (.*)")
_LOOSE_NAME = re.compile(r"([0-9]+)[\s._-]*(.*)")
_TEMP_NAME = re.compile(r"\.wri-[0-9a-f]{6}-(.+)")

SETTINGS_TEMPLATE = """\
# Settings for this book. wri notices changes as soon as you save.

title = {title}
# subtitle = ""
# author = ""

# A word-count goal for the whole book, shown as a progress bar.
# target = 60000

[compile]
# Where compiling writes the manuscript, relative to this folder.
# The default is the book's title with ".md" on the end.
# output = "manuscript.md"

# How section and chapter headings are written in the manuscript.
# Use {{title}}, {{number}} and {{roman}}. Chapters are numbered straight
# through the book rather than starting again in each section.
# section_heading = "Part {{roman}}: {{title}}"
# chapter_heading = "Chapter {{number}}: {{title}}"
"""


class BookError(Exception):
    """Something went wrong that the writer should be told about."""


@dataclass(frozen=True)
class Settings:
    """What ``wri.toml`` says about the book."""

    title: str
    subtitle: str = ""
    author: str = ""
    target: int = 0
    output: str = ""
    section_heading: str = "{title}"
    chapter_heading: str = "{title}"


@dataclass(frozen=True)
class Chapter:
    path: Path
    title: str

    @property
    def label(self) -> str:
        return self.title or "Untitled"


@dataclass(frozen=True)
class Section:
    path: Path
    title: str
    chapters: tuple[Chapter, ...] = ()

    @property
    def label(self) -> str:
        return self.title or "Untitled"


def parse_name(name: str) -> tuple[int, str] | None:
    """Split a numbered name like ``"03 The Middle"`` into ``(3, "The Middle")``.

    Returns None for names that don't start with a number.
    """
    match = _CANONICAL_NAME.fullmatch(name) or _LOOSE_NAME.fullmatch(name)
    if match is None:
        return None
    return int(match[1]), match[2].strip()


def format_name(number: int, title: str, width: int = 2) -> str:
    """The on-disk name for the item at position ``number``."""
    prefix = str(number).zfill(width)
    return f"{prefix} {title}" if title else prefix


def clean_title(title: str) -> str:
    """Tidy a title the writer typed, or raise BookError if it can't be used in a file name."""
    title = " ".join(title.split())
    if not title:
        raise BookError("The title can't be empty.")
    if "/" in title:
        raise BookError("Titles can't contain “/” because they become file names.")
    if any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise BookError("Titles can't contain control characters.")
    if len(title.encode()) > MAX_TITLE_BYTES:
        raise BookError("That title is too long to be a file name.")
    return title


def read_settings(root: Path) -> Settings:
    """Read ``wri.toml`` from the book folder ``root``."""
    try:
        data = tomllib.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise BookError(f"Couldn't read {CONFIG_FILE}: {error}") from error

    options = data.get("compile", {})
    if not isinstance(options, dict):
        raise BookError(f"[compile] in {CONFIG_FILE} should be a table.")

    def text(table: dict[str, Any], key: str) -> str:
        value = table.get(key, "")
        if not isinstance(value, str):
            raise BookError(f"{key} in {CONFIG_FILE} should be text in quotes.")
        return value.strip()

    target = data.get("target", 0)
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise BookError(f"target in {CONFIG_FILE} should be a whole number of words.")

    return Settings(
        title=text(data, "title") or root.name,
        subtitle=text(data, "subtitle"),
        author=text(data, "author"),
        target=target,
        output=text(options, "output"),
        section_heading=text(options, "section_heading") or "{title}",
        chapter_heading=text(options, "chapter_heading") or "{title}",
    )


class Book:
    """A book folder loaded into memory.

    Methods that change the structure do so on disk straight away and then
    reload. Call ``reload()`` to pick up changes made by other programs.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.settings = Settings(title=self.root.name)
        self.settings_error: str | None = None
        self.sections: list[Section] = []
        self._word_counts: dict[Path, tuple[tuple[int, int], int]] = {}
        _recover(self.root)
        for folder, _ in _scan(self.root, folders=True):
            _recover(folder)
        self.reload()

    @staticmethod
    def find(start: Path) -> Path | None:
        """Find the book folder at or above ``start``, the way git finds a repository."""
        if not start.exists():
            return None
        start = start.resolve()
        for folder in (start, *start.parents):
            if (folder / CONFIG_FILE).is_file():
                return folder
        return None

    @classmethod
    def create(cls, root: Path, title: str | None = None) -> Book:
        """Make ``root`` into a book, creating the folder if needed."""
        root.mkdir(parents=True, exist_ok=True)
        config = root / CONFIG_FILE
        if not config.exists():
            title = title or root.resolve().name
            text = SETTINGS_TEMPLATE.format(title=json.dumps(title, ensure_ascii=False))
            config.write_text(text, encoding="utf-8")
        return cls(root)

    @staticmethod
    def would_be_sections(folder: Path) -> list[str]:
        """The names of folders inside ``folder`` that would become sections of a book there."""
        return [path.name for path, _ in _scan(folder, folders=True)]

    # Reading

    def reload(self) -> None:
        """Re-read the structure and settings from disk."""
        try:
            self.settings = read_settings(self.root)
            self.settings_error = None
        except BookError as error:
            self.settings_error = str(error)
        self.sections = [
            Section(folder, title, tuple(Chapter(p, t) for p, t in _scan(folder, folders=False)))
            for folder, title in _scan(self.root, folders=True)
        ]
        current = {chapter.path for section in self.sections for chapter in section.chapters}
        for path in self._word_counts.keys() - current:
            del self._word_counts[path]

    def fingerprint(self) -> tuple[object, ...]:
        """A cheap summary of everything on disk that matters, for noticing outside changes."""
        parts: list[object] = [_stat_key(self.root / CONFIG_FILE)]
        for folder, _ in _scan(self.root, folders=True):
            parts.append(folder.name)
            parts.extend((path.name, _stat_key(path)) for path, _ in _scan(folder, folders=False))
        return tuple(parts)

    @property
    def chapter_count(self) -> int:
        return sum(len(section.chapters) for section in self.sections)

    def words(self, chapter: Chapter) -> int:
        """How many words are in ``chapter``, cached until the file changes."""
        key = _stat_key(chapter.path)
        if key is None:
            return 0
        cached = self._word_counts.get(chapter.path)
        if cached and cached[0] == key:
            return cached[1]
        count = count_words(read_markdown(chapter.path))
        self._word_counts[chapter.path] = (key, count)
        return count

    def section_words(self, section: Section) -> int:
        return sum(self.words(chapter) for chapter in section.chapters)

    def total_words(self) -> int:
        return sum(self.section_words(section) for section in self.sections)

    # Sections

    def add_section(self, title: str, index: int | None = None) -> int:
        """Add an empty section at ``index`` (default: the end). Returns its index."""
        title = clean_title(title)
        index = _clamp(len(self.sections) if index is None else index, len(self.sections))
        items = self._section_items()
        items.insert(index, (None, title, ""))
        with _friendly_errors():
            _arrange(self.root, items, new_folders=True)
        self.reload()
        return index

    def rename_section(self, index: int, title: str) -> None:
        title = clean_title(title)
        items = self._section_items()
        items[index] = (items[index][0], title, "")
        with _friendly_errors():
            _arrange(self.root, items)
        self.reload()

    def move_section(self, index: int, new_index: int) -> int:
        """Move a section to ``new_index``. Returns where it ended up."""
        new_index = _clamp(new_index, len(self.sections) - 1)
        if new_index != index:
            items = self._section_items()
            items.insert(new_index, items.pop(index))
            with _friendly_errors():
                _arrange(self.root, items)
            self.reload()
        return new_index

    def delete_section(self, index: int) -> Path:
        """Move a section and its chapters to the book's trash. Returns where it went."""
        items = self._section_items()
        del items[index]
        with _friendly_errors():
            trashed = self._trash(self.sections[index].path)
            _arrange(self.root, items)
        self.reload()
        return trashed

    # Chapters

    def add_chapter(self, section_index: int, title: str, index: int | None = None) -> int:
        """Create an empty chapter file at ``index`` (default: the end). Returns its index."""
        title = clean_title(title)
        section = self.sections[section_index]
        count = len(section.chapters)
        index = _clamp(count if index is None else index, count)
        items = self._chapter_items(section)
        items.insert(index, (None, title, ".md"))
        with _friendly_errors():
            _arrange(section.path, items)
        self.reload()
        return index

    def rename_chapter(self, section_index: int, index: int, title: str) -> None:
        title = clean_title(title)
        section = self.sections[section_index]
        items = self._chapter_items(section)
        path, _, suffix = items[index]
        items[index] = (path, title, suffix)
        with _friendly_errors():
            _arrange(section.path, items)
        self.reload()

    def move_chapter(self, section_index: int, index: int, new_index: int) -> int:
        """Move a chapter within its section. Returns where it ended up."""
        section = self.sections[section_index]
        new_index = _clamp(new_index, len(section.chapters) - 1)
        if new_index != index:
            items = self._chapter_items(section)
            items.insert(new_index, items.pop(index))
            with _friendly_errors():
                _arrange(section.path, items)
            self.reload()
        return new_index

    def move_chapter_to_section(self, section_index: int, index: int, target_index: int) -> int:
        """Move a chapter to the end of another section. Returns its index there."""
        if target_index == section_index:
            return index
        source = self.sections[section_index]
        target = self.sections[target_index]
        chapter = source.chapters[index]
        staged = target.path / f".wri-{secrets.token_hex(3)}-{chapter.path.name}"
        target_items = self._chapter_items(target)
        target_items.append((staged, chapter.title, chapter.path.suffix))
        source_items = self._chapter_items(source)
        del source_items[index]
        with _friendly_errors():
            chapter.path.rename(staged)
            try:
                _arrange(target.path, target_items)
            except BaseException:
                staged.rename(chapter.path)
                raise
            _arrange(source.path, source_items)
        self.reload()
        return len(target_items) - 1

    def delete_chapter(self, section_index: int, index: int) -> Path:
        """Move a chapter to the book's trash. Returns where it went."""
        section = self.sections[section_index]
        items = self._chapter_items(section)
        del items[index]
        with _friendly_errors():
            trashed = self._trash(section.chapters[index].path, section.path.name)
            _arrange(section.path, items)
        self.reload()
        return trashed

    # Helpers

    def _section_items(self) -> list[_Item]:
        return [(section.path, section.title, "") for section in self.sections]

    @staticmethod
    def _chapter_items(section: Section) -> list[_Item]:
        return [(chapter.path, chapter.title, chapter.path.suffix) for chapter in section.chapters]

    def _trash(self, path: Path, *within: str) -> Path:
        """Move ``path`` into ``.trash/<date and time>/`` inside the book."""
        folder = self.root / TRASH_DIR / datetime.now().strftime("%Y-%m-%d %H.%M.%S")
        folder = folder.joinpath(*within)
        folder.mkdir(parents=True, exist_ok=True)
        destination = _unused(folder / path.name, is_folder=path.is_dir())
        path.rename(destination)
        return destination


# An item to arrange: its current path (None to create it), its title and its suffix.
type _Item = tuple[Path | None, str, str]


def _arrange(folder: Path, items: Sequence[_Item], *, new_folders: bool = False) -> list[Path]:
    """Rename ``items`` so that each name starts with its position in the list.

    Items without a path are created, as folders if ``new_folders`` is set and
    as empty files otherwise. Everything that changes name is first moved to a
    temporary name, so swapping two items never collides. Returns the final paths.
    """
    width = max(2, len(str(len(items))))
    targets = [
        folder / (format_name(number, title, width) + suffix)
        for number, (_, title, suffix) in enumerate(items, 1)
    ]
    existing = [path for path, _, _ in items if path is not None]
    for target in targets:
        if target.exists() and not any(_same_file(target, path) for path in existing):
            raise BookError(f"Can't use the name “{target.name}”: something else already has it.")

    token = secrets.token_hex(3)
    staged: list[tuple[Path | None, Path, Path | None]] = []  # (temporary, target, original)
    try:
        for (path, _, _), target in zip(items, targets, strict=True):
            if path is None:
                staged.append((None, target, None))
            elif _TEMP_NAME.fullmatch(path.name):
                staged.append((path, target, None))
            elif path.name != target.name:
                temporary = path.with_name(f".wri-{token}-{path.name}")
                path.rename(temporary)
                staged.append((temporary, target, path))
    except OSError:
        for temporary, _, original in staged:
            if temporary is not None and original is not None:
                temporary.rename(original)
        raise

    for temporary, target, _ in staged:
        if temporary is not None:
            temporary.rename(target)
        elif new_folders:
            target.mkdir()
        else:
            target.touch(exist_ok=False)
    return targets


def _scan(folder: Path, *, folders: bool) -> list[tuple[Path, str]]:
    """The numbered sub-folders (or Markdown files) in ``folder`` in order, with their titles."""
    found: list[tuple[int, str, str, Path, str]] = []
    try:
        entries = list(os.scandir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if folders:
            if not entry.is_dir():
                continue
            stem = entry.name
        else:
            suffix = _chapter_suffix(entry.name)
            if suffix is None or not entry.is_file():
                continue
            stem = entry.name.removesuffix(suffix)
        parsed = parse_name(stem)
        if parsed is not None:
            number, title = parsed
            found.append((number, title.casefold(), entry.name, Path(entry.path), title))
    found.sort()
    return [(path, title) for *_, path, title in found]


def _chapter_suffix(name: str) -> str | None:
    lowered = name.lower()
    for suffix in CHAPTER_SUFFIXES:
        if lowered.endswith(suffix) and len(name) > len(suffix):
            return name[-len(suffix) :]
    return None


def _recover(folder: Path) -> None:
    """Restore the names of anything a crashed wri left half-renamed in ``folder``."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        match = _TEMP_NAME.fullmatch(entry.name)
        if match:
            destination = _unused(folder / match[1], is_folder=entry.is_dir())
            Path(entry.path).rename(destination)


def _unused(path: Path, *, is_folder: bool) -> Path:
    """``path``, or ``path`` with " (2)", " (3)"… added if that name is taken."""
    if not path.exists():
        return path
    suffix = "" if is_folder else (_chapter_suffix(path.name) or path.suffix)
    stem = path.name.removesuffix(suffix) if suffix else path.name
    number = 2
    while (candidate := path.with_name(f"{stem} ({number}){suffix}")).exists():
        number += 1
    return candidate


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _clamp(value: int, highest: int) -> int:
    return max(0, min(value, highest))


@contextmanager
def _friendly_errors() -> Iterator[None]:
    """Turn file system errors into BookErrors with a readable message."""
    try:
        yield
    except OSError as error:
        name = Path(error.filename).name if error.filename else ""
        detail = error.strerror or str(error)
        raise BookError(f"{detail}: {name}" if name else detail) from error
