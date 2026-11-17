"""Deterministic layout compilation.

The same design must always produce the same layout: blocks keep the design
order, an explicit `pos` is honoured, and everything else fills the grid from the
top-left. When the grid cannot fit a block the compiler fails instead of placing
it off-canvas, because a visual outside the page is invisible but still a defect
that reaches Desktop.
"""

from __future__ import annotations

import json

import pytest

from agentic_bi.constructor.design import Design
from agentic_bi.constructor.layout import GUTTER, MARGIN, ROW_H, compile_design


def _design(page: dict[str, object]) -> Design:
    return Design.from_dict({"pages": [page]})


def _card(kind: str = "card", **extra: object) -> dict[str, object]:
    block: dict[str, object] = {"kind": kind, "table": "Sales", "value": "amount"}
    block.update(extra)
    return block


class TestPlacement:
    def test_auto_placement_fills_two_columns_then_a_new_row(self) -> None:
        design = _design({"name": "p", "visuals": [_card(), _card(), _card()]})
        compiled = compile_design(design)
        cell = (1280 - 2 * MARGIN - GUTTER) // 2
        first, second, third = compiled.positions.values()
        assert first == (MARGIN, MARGIN, cell, ROW_H)
        assert second[0] == MARGIN + cell + GUTTER and second[1] == MARGIN
        assert third[0] == MARGIN and third[1] == MARGIN + ROW_H + GUTTER

    def test_an_explicit_position_is_kept_verbatim(self) -> None:
        design = _design({"name": "p", "visuals": [_card(pos=[100, 40, 300, 200])]})
        assert compile_design(design).positions["p_1"] == (100, 40, 300, 200)

    def test_an_explicit_position_reserves_its_cell(self) -> None:
        design = _design(
            {
                "name": "p",
                "visuals": [
                    _card(pos=[MARGIN, MARGIN, 620, ROW_H]),
                    _card(),
                ],
            }
        )
        positions = compile_design(design).positions
        cell = (1280 - 2 * MARGIN - GUTTER) // 2
        assert positions["p_2"][0] == MARGIN + cell + GUTTER

    def test_span_wider_than_the_grid_is_clamped(self) -> None:
        design = _design({"name": "p", "visuals": [_card(span=5)]})
        _, _, width, _ = compile_design(design).positions["p_1"]
        assert width == 1280 - 2 * MARGIN

    def test_a_narrow_page_uses_one_column(self) -> None:
        design = _design({"name": "p", "width": 600, "visuals": [_card(), _card()]})
        second = compile_design(design).positions["p_2"]
        assert second[0] == MARGIN
        assert second[1] == MARGIN + ROW_H + GUTTER

    def test_a_page_without_a_free_cell_fails_instead_of_overflowing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every row of the (deliberately tiny) grid is covered by an explicit
        # position, so the auto-placed block has nowhere to go.
        import agentic_bi.constructor.layout as layout_module

        monkeypatch.setattr(layout_module, "_MAX_ROWS", 2)
        filling = [_card(pos=[MARGIN, MARGIN + i * 300, 1280, 300]) for i in range(4)]
        design = _design({"name": "p", "visuals": [*filling, _card()]})
        with pytest.raises(ValueError) as exc:
            compile_design(design)
        assert "no free slot" in str(exc.value)

    def test_a_page_too_narrow_for_its_margins_is_rejected(self) -> None:
        design = _design({"name": "p", "width": 30, "visuals": [_card()]})
        with pytest.raises(ValueError) as exc:
            compile_design(design)
        assert "too narrow" in str(exc.value)


class TestCompiledLayout:
    def test_the_layout_carries_one_section_per_page_in_order(self) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {"name": "p1", "title": "One", "visuals": [_card()]},
                    {"name": "p2", "title": "Two", "visuals": [_card()]},
                ]
            }
        )
        compiled = compile_design(design)
        assert [s["displayName"] for s in compiled.layout["sections"]] == ["One", "Two"]
        assert [s["ordinal"] for s in compiled.layout["sections"]] == [0, 1]

    def test_page_size_is_a_minimum_and_grows_with_the_blocks(self) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {
                        "name": "p",
                        "width": 1280,
                        "height": 400,
                        "visuals": [_card(), _card(), _card()],
                    }
                ]
            }
        )
        section = compile_design(design).layout["sections"][0]
        assert section["width"] >= 1280
        assert section["height"] > 400

    def test_layout_bytes_are_utf16le_and_round_trip(self) -> None:
        design = _design({"name": "p", "title": "Продажи", "visuals": [_card()]})
        compiled = compile_design(design)
        raw = compiled.layout_bytes()
        assert json.loads(raw.decode("utf-16-le"))["sections"][0]["displayName"] == (
            "Продажи"
        )

    def test_page_counts_matches_the_design(self) -> None:
        design = _design({"name": "p", "visuals": [_card(), _card()]})
        assert compile_design(design).page_counts() == {"p": 2}

    def test_two_compilations_place_blocks_identically(self) -> None:
        design = _design({"name": "p", "visuals": [_card(), _card(span=2)]})
        first = compile_design(design).positions
        second = compile_design(design).positions
        assert first == second
