"""A half-built `Visual` must fail loudly, not render a partial chart.

`Visual.__post_init__` validates the initial state, but the dataclass is mutable:
clearing `axis`/`value` afterwards used to reach the query builders as `None` and
produce `Sum(table.None)` or a dropped projection - a blank visual with no
diagnostic. `_visual_config` now raises a `ValueError` naming the kind and field.
"""

from __future__ import annotations

import pytest

from agentic_bi.engine.layout_visual import Visual, _visual_config


def _clear(visual: Visual, field: str) -> Visual:
    setattr(visual, field, None)
    return visual


@pytest.mark.parametrize(
    ("kind", "kwargs", "field", "message"),
    [
        ("stackedBar", {"axis": "a", "value": "b"}, "value", "value column"),
        ("column", {"axis": "a", "value": "b"}, "axis", "category column"),
        ("slicer", {"axis": "a"}, "axis", "axis column"),
        ("treemap", {"axis": "a", "value": "b"}, "axis", "group column"),
        ("card", {"value": "b"}, "value", "value column"),
        ("gauge", {"value": "b"}, "value", "value column"),
        ("kpi", {"value": "b"}, "value", "value column"),
    ],
)
def test_missing_required_field_raises(
    kind: str, kwargs: dict, field: str, message: str
) -> None:
    visual = _clear(Visual(kind=kind, table="T", **kwargs), field)
    with pytest.raises(ValueError, match=f"visual '{kind}': {message} is missing"):
        _visual_config(visual)


def test_scatter_reports_the_missing_x_role() -> None:
    visual = Visual(kind="scatter", table="T", x="a", y="b")
    visual.x = None
    with pytest.raises(ValueError, match="visual 'scatter': x column is missing"):
        _visual_config(visual)


def test_scatter_reports_the_missing_y_role() -> None:
    visual = Visual(kind="scatter", table="T", x="a", y="b")
    visual.y = None
    with pytest.raises(ValueError, match="visual 'scatter': y column is missing"):
        _visual_config(visual)


def test_a_complete_visual_still_builds_every_required_projection() -> None:
    visual = Visual(kind="stackedBar", table="T", axis="a", value="b", series="c")
    projections = _visual_config(visual)["singleVisual"]["projections"]
    assert set(projections) == {"Category", "Y", "Series"}
    assert all(role for role in projections.values())


def test_a_measure_still_satisfies_the_value_role_without_value() -> None:
    assert Visual(kind="card", table="T", measure="m").value is None
    projections = _visual_config(Visual(kind="card", table="T", measure="m"))
    assert projections["singleVisual"]["projections"]["Values"]
