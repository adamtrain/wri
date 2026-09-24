import io
from pathlib import Path

import pytest

from wri import cli
from wri.book import CONFIG_FILE, Book, BookError

from conftest import make_book


def test_compile_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "Hello there."}})
    assert cli.main(["compile", str(book.root), "-o", "-"]) == 0
    assert "## a1\n\nHello there." in capsys.readouterr().out


def test_compile_to_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    book = make_book(tmp_path / "book", {"A": {"a1": "Hello there."}})
    assert cli.main(["compile", str(book.root / "01 A")]) == 0
    assert (book.root / "Test Book.md").is_file()
    assert "1 section, 1 chapter, 2 words" in capsys.readouterr().out


def test_compile_without_a_book(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["compile", str(tmp_path)]) == 1
    assert "No book found" in capsys.readouterr().err


def test_start_book_needs_a_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(BookError, match="No book found"):
        cli.start_book(tmp_path / "new")


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def answer(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    """Pretend to be a terminal where the writer types ``reply``; returns the questions asked."""
    questions: list[str] = []
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda question: questions.append(question) or reply)
    return questions


def test_start_book_in_a_new_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    questions = answer(monkeypatch, "")
    root = cli.start_book(tmp_path / "Night Thoughts")
    assert root == (tmp_path / "Night Thoughts").resolve()
    assert "[Y/n]" in questions[0]
    assert Book(root).settings.title == "Night Thoughts"


def test_start_book_asks_before_adopting_a_full_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "70-79 Computer").mkdir()
    questions = answer(monkeypatch, "")
    assert cli.start_book(tmp_path) is None
    assert "[y/N]" in questions[0]
    assert "70-79 Computer" in capsys.readouterr().out
    assert not (tmp_path / CONFIG_FILE).exists()
    assert (tmp_path / "70-79 Computer").is_dir()
