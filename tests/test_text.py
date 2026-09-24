from wri.text import count_words, normalize, split_front_matter, tidy_headings, without_title


def test_count_words() -> None:
    assert count_words("") == 0
    assert count_words("Hello, world!") == 2
    assert count_words("# Title\n\n- one\n- two\n\n---\n\n*Emphasis* and **bold**.") == 6
    assert count_words("don't stop — ever") == 3


def test_count_words_skips_front_matter_and_comments() -> None:
    text = "---\nstatus: draft\nnotes: lots of words here\n---\nThe real text.<!-- a note -->"
    assert count_words(text) == 3


def test_split_front_matter() -> None:
    assert split_front_matter("---\ntitle: X\n---\nBody") == ("---\ntitle: X\n---", "Body")
    # A rule at the top of a chapter is not front matter.
    assert split_front_matter("---\n\nText\n---\n")[0] == ""
    # Nor is an unfinished block.
    assert split_front_matter("---\ntitle: X\nBody")[0] == ""


def test_normalize() -> None:
    assert normalize("﻿a\r\nb\rc") == "a\nb\nc"


def test_headings_move_to_the_top_level() -> None:
    assert tidy_headings("# One\n\ntext\n\n## Two", top_level=3) == "### One\n\ntext\n\n#### Two"
    assert tidy_headings("### Already\n#### Fine", top_level=3) == "### Already\n#### Fine"
    assert tidy_headings("#### Deep", top_level=3) == "### Deep"
    assert tidy_headings("# a\n## b\n### c\n#### d\n##### e", top_level=3).split("\n")[-1] == (
        "###### e"
    )


def test_headings_leave_code_and_hashtags_alone() -> None:
    code = "```python\n# a comment\n```\n\n~~~~\n# also code\n~~~\n# still code\n~~~~\n#hashtag"
    assert tidy_headings(f"# Heading\n\n{code}", top_level=3) == f"### Heading\n\n{code}"


def test_setext_headings_become_atx() -> None:
    text = "Big\n===\n\nSmaller\n---\n\nText\n\n---\n\nAfter a rule"
    assert tidy_headings(text, top_level=3) == (
        "### Big\n\n#### Smaller\n\nText\n\n---\n\nAfter a rule"
    )


def test_title_heading_is_dropped() -> None:
    text = "\n# Why We Sleep #\n\nText\n\n## Why We Sleep"
    assert tidy_headings(text, top_level=3, title="why  we sleep") == "\n\nText\n\n### Why We Sleep"
    assert without_title("Intro\n=====\n\nText", "Intro") == "\nText"
    assert without_title("Text first\n\n# Intro", "Intro") == "Text first\n\n# Intro"
