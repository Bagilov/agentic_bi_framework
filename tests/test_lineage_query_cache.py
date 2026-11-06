"""Brand-metrics cache: only success is cached, failures stay retryable.

A transient page-analysis or audit failure used to be cached as an empty
result for the lifetime of the instance, so one bad call disabled brand metrics
forever. `QueryMixin` also has to keep working for duck-typed models that never
initialise `_brand_cache`.
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_query import PageAnalysis, QueryMixin
from agentic_bi.lineage.lineage_types import Page


class _Ctx(QueryMixin):
    def __init__(self) -> None:
        self.pages = [Page(index=1, name="Overview", visuals=[])]
        self._brand_cfg = None
        self._brand_cache = None

    def _collect_visual_fonts(self, page: Page) -> list[str]:
        return []


def test_a_failed_audit_is_retried_and_only_success_is_cached(monkeypatch) -> None:
    from agentic_bi.lineage import lineage_query

    calls = {"n": 0}

    def flaky_audit(pages: list[dict], cfg: object) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("brand rules temporarily unavailable")
        return {
            "summary": {"pages": 1},
            "pages": [{"name": "Overview", "metrics": {"level": "ok"}}],
        }

    monkeypatch.setattr(lineage_query, "brand_audit_pages", flaky_audit)
    ctx = _Ctx()

    assert ctx.brand_metrics() == {"summary": {}, "pages": {}}
    assert ctx._brand_cache is None

    second = ctx.brand_metrics()
    assert second == {"summary": {"pages": 1}, "pages": {"Overview": {"level": "ok"}}}
    assert ctx._brand_cache is second
    assert ctx.brand_metrics() is second
    assert calls["n"] == 2


class _FlakyPageAnalysis(_Ctx):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def page_analysis(self) -> list[PageAnalysis]:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("layout parse failed")
        return [
            {
                "page": "Overview",
                "elements": {},
                "n_elements": 0,
                "colors": [],
            }
        ]


def test_a_failed_page_analysis_is_guarded_and_retried(monkeypatch) -> None:
    from agentic_bi.lineage import lineage_query

    monkeypatch.setattr(
        lineage_query,
        "brand_audit_pages",
        lambda pages, cfg: {"summary": {"pages": 1}, "pages": []},
    )
    ctx = _FlakyPageAnalysis()

    assert ctx.brand_metrics() == {"summary": {}, "pages": {}}
    assert ctx._brand_cache is None

    assert ctx.brand_metrics() == {"summary": {"pages": 1}, "pages": {}}
    assert ctx._brand_cache is not None
    assert ctx.attempts == 2


def test_brand_metrics_works_without_the_cache_attribute(monkeypatch) -> None:
    from agentic_bi.lineage import lineage_query

    class _NoCacheCtx(QueryMixin):
        def __init__(self) -> None:
            self.pages: list[Page] = []
            self._brand_cfg = None

        def _collect_visual_fonts(self, page: Page) -> list[str]:
            return []

    monkeypatch.setattr(
        lineage_query,
        "brand_audit_pages",
        lambda pages, cfg: {"summary": {}, "pages": []},
    )
    ctx = _NoCacheCtx()
    assert not hasattr(ctx, "_brand_cache")

    result = ctx.brand_metrics()
    assert result == {"summary": {}, "pages": {}}
    assert ctx._brand_cache is result
