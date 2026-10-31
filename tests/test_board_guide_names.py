"""Name/stem tests for the annotated board guide (`board_guide`).

Page names come from untrusted `Report/Layout`; these tests pin how they are
sanitized into filesystem-safe, unique stems so `guide_<stem>.html` and
`page_<stem>.png` never silently overwrite each other.
"""

from __future__ import annotations

from agentic_bi.board_guide import safe_name, unique_stems
from agentic_bi.board_guide.guide_geometry import GuidePage
from agentic_bi.board_guide.guide_names import unique_stems_for_names


def test_safe_name_strips_separators_and_keeps_ascii() -> None:
    assert safe_name("Sales/Overview 2026") == "Sales_Overview_2026"
    assert safe_name("   ") == "page"


def test_safe_name_keeps_non_latin_letters() -> None:
    """A Cyrillic page must not collapse to a constant `page` stem.

    Collapsing made every Cyrillic page share one file name, so the guide
    overwrote `guide_page.html` and the index linked to the wrong page.
    """
    assert safe_name("Прибыль по регионам") == "Прибыль_по_регионам"
    assert safe_name("Продажи") != safe_name("Прибыль")
    assert safe_name("Отчёт/2026") == "Отчёт_2026"


def test_safe_name_drops_path_traversal() -> None:
    """A page name must never escape the output directory."""
    assert "/" not in safe_name("../etc/passwd")
    assert "\\" not in safe_name("..\\..\\win")
    assert ".." not in safe_name("../etc/passwd")
    assert safe_name("...") == "page"


def test_unique_stems_disambiguates_colliding_names() -> None:
    """Two page names that sanitize alike still get distinct stems, in order."""
    pages = [
        GuidePage(name="A/B"),
        GuidePage(name="A B"),
        GuidePage(name="A_B"),
        GuidePage(name="Other"),
    ]
    assert unique_stems(pages) == ["A_B", "A_B-2", "A_B-3", "Other"]


def test_unique_stems_does_not_collide_with_its_own_suffix() -> None:
    """A page literally named `A_B-2` must not reuse the suffix of a duplicate.

    The old numbering appended `-2` without checking whether that name was
    itself an original stem, so two pages shared one `guide_<stem>.html` and the
    index linked two rows to the same file.
    """
    assert unique_stems_for_names(["A_B", "A_B", "A_B-2"]) == [
        "A_B",
        "A_B-2",
        "A_B-2-2",
    ]
    assert unique_stems_for_names(["Детали", "Детали", "Детали-2"]) == [
        "Детали",
        "Детали-2",
        "Детали-2-2",
    ]


def test_unique_stems_separates_case_only_names() -> None:
    """`Sales` and `sales` must not map to one file on a case-insensitive FS."""
    assert unique_stems_for_names(["Sales", "sales"]) == ["Sales", "sales-2"]


def test_safe_name_bounds_long_names() -> None:
    """A very long page name must not make `guide_<stem>.html` exceed 255 bytes.

    An unbounded stem made the whole run abort with `OSError` mid-loop, leaving
    a partial guide without an index.
    """
    stem = safe_name("Z" * 300)
    assert len(f"guide_{stem}.html".encode()) <= 200
    assert len(stem.encode("utf-8")) <= 120
    assert safe_name("Z" * 300) != safe_name("Z" * 299 + "Y")


def test_unique_stems_is_stable_for_distinct_names() -> None:
    pages = [GuidePage(name="Overview"), GuidePage(name="Details")]
    assert unique_stems(pages) == ["Overview", "Details"]


def test_unique_stems_for_names_matches_pages() -> None:
    """The name-based helper and the page-based one must agree."""
    pages = [GuidePage(name="A/B"), GuidePage(name="A B")]
    assert unique_stems(pages) == unique_stems_for_names(["A/B", "A B"])
