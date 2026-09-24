"""Small Markdown helpers: reading chapters, counting words and tidying headings."""

from __future__ import annotations

import re
from pathlib import Path

_WORDISH = re.compile(r"\w")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_YAML_KEY = re.compile(r"[A-Za-z_][\w -]*:(?:\s|$)")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_ATX_HEADING = re.compile(r"( {0,3})(#{1,6})(?=[ \t]|$)(.*)")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r" {0,3}(=+|-+)[ \t]*")
# Lines that start something other than a paragraph: headings, quotes, tables,
# HTML, list items, fences and indented code.
_NOT_PARAGRAPH = re.compile(
    r" {0,3}(?:[#>|<]|[-*+](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$)|`{3}|~{3})| {4}|\t"
)


def plural(count: int, noun: str) -> str:
    """``"1 word"``, ``"2 words"``, ``"1,200 words"``."""
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def normalize(text: str) -> str:
    """Drop a byte-order mark and use Unix newlines."""
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def read_markdown(path: Path) -> str:
    """Read a Markdown file as normalized text, or ``""`` if it has gone missing."""
    try:
        return normalize(path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return ""


def split_front_matter(text: str) -> tuple[str, str]:
    """Split a leading YAML front matter block from ``text``: ``(front_matter, body)``."""
    lines = text.split("\n")
    if len(lines) < 3 or lines[0].rstrip() != "---" or not _YAML_KEY.match(lines[1]):
        return "", text
    for index in range(2, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return "\n".join(lines[: index + 1]), "\n".join(lines[index + 1 :])
    return "", text


def body(text: str) -> str:
    """The part of a chapter meant for readers: everything after any front matter."""
    return split_front_matter(text)[1]


def count_words(text: str) -> int:
    """Count the words a reader would see. Front matter and HTML comments don't count."""
    prose = _COMMENT.sub(" ", body(text))
    return sum(1 for token in prose.split() if _WORDISH.search(token))


def heading_text(line: str) -> str | None:
    """The text of an ATX heading line such as ``## Title ##``, or None for other lines."""
    match = _ATX_HEADING.fullmatch(line)
    if match is None:
        return None
    return " ".join(_CLOSING_HASHES.sub("", match[3].strip()).split())


def tidy_headings(text: str, top_level: int, title: str = "") -> str:
    """Prepare a chapter's headings to sit inside a larger document.

    Setext headings become ATX headings, a first heading that just repeats
    ``title`` is dropped, and every heading moves up or down together so the
    biggest one is at ``top_level``. Fenced code blocks are left untouched.
    """
    lines, regular = _parse(text)
    _drop_title(lines, regular, title)
    matches = [
        _ATX_HEADING.fullmatch(line) if ok else None
        for line, ok in zip(lines, regular, strict=True)
    ]
    levels = [len(match[2]) for match in matches if match]
    if levels:
        shift = top_level - min(levels)
        for index, match in enumerate(matches):
            if match:
                level = min(6, max(1, len(match[2]) + shift))
                lines[index] = f"{match[1]}{'#' * level}{match[3]}"
    return "\n".join(lines)


def without_title(text: str, title: str) -> str:
    """``text`` without a first heading that only repeats ``title``."""
    lines, regular = _parse(text)
    _drop_title(lines, regular, title)
    return "\n".join(lines)


def _parse(text: str) -> tuple[list[str], list[bool]]:
    """Split text into lines, with setext headings made ATX, and flags for lines outside fences."""
    lines = text.split("\n")
    return _setext_to_atx(lines, _outside_fences(lines))


def _drop_title(lines: list[str], regular: list[bool], title: str) -> None:
    """Remove the first heading from ``lines`` if it is just ``title`` again."""
    wanted = " ".join(title.split()).casefold()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        found = heading_text(line) if regular[index] else None
        if wanted and found is not None and found.casefold() == wanted:
            del lines[index], regular[index]
        return


def _outside_fences(lines: list[str]) -> list[bool]:
    """For each line, whether it is ordinary Markdown rather than part of a code fence."""
    regular: list[bool] = []
    fence = ""
    for line in lines:
        match = _FENCE.match(line)
        if not fence:
            if match:
                fence = match[1]
            regular.append(match is None)
            continue
        regular.append(False)
        if (
            match
            and line.strip() == match[1]
            and match[1][0] == fence[0]
            and len(match[1]) >= len(fence)
        ):
            fence = ""
    return regular


def _setext_to_atx(lines: list[str], regular: list[bool]) -> tuple[list[str], list[bool]]:
    """Rewrite one-line setext headings (a line underlined with === or ---) as ATX headings."""
    out_lines: list[str] = []
    out_regular: list[bool] = []
    for line, ok in zip(lines, regular, strict=True):
        underline = _SETEXT_UNDERLINE.fullmatch(line) if ok else None
        if underline and _ends_with_one_line_paragraph(out_lines, out_regular):
            level = 1 if underline[1][0] == "=" else 2
            out_lines[-1] = f"{'#' * level} {out_lines[-1].strip()}"
            continue
        out_lines.append(line)
        out_regular.append(ok)
    return out_lines, out_regular


def _ends_with_one_line_paragraph(lines: list[str], regular: list[bool]) -> bool:
    if not lines or not regular[-1]:
        return False
    last = lines[-1]
    if not last.strip() or _NOT_PARAGRAPH.match(last):
        return False
    if len(lines) == 1 or not regular[-2]:
        return True
    before = lines[-2]
    return not before.strip() or heading_text(before) is not None
