"""The ``wri`` command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wri import __version__
from wri.book import CONFIG_FILE, Book, BookError
from wri.compile import compile_book, write_manuscript
from wri.text import plural

DESCRIPTION = "Outline and write nonfiction books as folders of Markdown files."
EPILOG = """\
commands:
  wri [BOOK]                open the book in BOOK (default: this folder)
  wri compile [BOOK] [-o F] stitch the book into one Markdown file

A book is a folder with a wri.toml file in it. Run wri in an empty or new
folder to start one.
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["compile"]:
            return compile_command(argv[1:])
        return open_command(argv)
    except BookError as error:
        print(f"wri: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def open_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="wri",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("book", nargs="?", default=".", help="the book's folder")
    parser.add_argument("--version", action="version", version=f"wri {__version__}")
    args = parser.parse_args(argv)

    root = Book.find(Path(args.book)) or start_book(Path(args.book))
    if root is None:
        return 1

    from wri.app import WriApp  # Textual takes a moment to import; only load it when needed.

    WriApp(root).run()
    return 0


def compile_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="wri compile",
        description="Stitch every chapter into one Markdown file, with section and chapter titles.",
    )
    parser.add_argument("book", nargs="?", default=".", help="the book's folder")
    parser.add_argument(
        "-o",
        "--output",
        help="where to save it (default: from wri.toml, else the book's title + .md); - for stdout",
    )
    args = parser.parse_args(argv)

    root = Book.find(Path(args.book))
    if root is None:
        raise BookError(f"No book found at {args.book} (a book is a folder with a {CONFIG_FILE}).")
    book = Book(root)
    if book.settings_error:
        print(f"wri: warning: {book.settings_error}", file=sys.stderr)

    if args.output == "-":
        sys.stdout.write(compile_book(book))
        return 0
    result = write_manuscript(book, Path(args.output) if args.output else None)
    counts = [plural(result.sections, "section"), plural(result.chapters, "chapter")]
    print(f"Wrote {result.path}: {', '.join(counts)}, {plural(result.words, 'word')}.")
    return 0


def start_book(folder: Path) -> Path | None:
    """Offer to start a new book in ``folder``. Returns the book's folder if one was made."""
    if folder.exists() and not folder.is_dir():
        raise BookError(f"{folder} is a file, not a folder.")
    if not sys.stdin.isatty():
        raise BookError(f"No book found at {folder} (a book is a folder with a {CONFIG_FILE}).")

    where = folder.resolve()
    if not folder.exists():
        question, default = f"Start a new book in {where}?", True
    elif not any(folder.iterdir()):
        question, default = f"Start a new book in the empty folder {where}?", True
    else:
        print(f"{where} isn't a wri book yet (it has no {CONFIG_FILE}).")
        if sections := Book.would_be_sections(folder):
            shown = ", ".join(sections[:5]) + (", …" if len(sections) > 5 else "")
            print(f"Its numbered folders would become sections and be renumbered: {shown}")
        question, default = "Turn it into a book?", False

    if not ask(question, default=default):
        return None
    book = Book.create(folder)
    print(f"Started “{book.settings.title}”. Book settings are in {CONFIG_FILE}.")
    return book.root


def ask(question: str, *, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return False
    return default if not answer else answer in ("y", "yes")
