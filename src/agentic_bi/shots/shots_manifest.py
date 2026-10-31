"""Manifest of a rendered figure set: sizes, hashes and a verification pass.

A figure set is only trustworthy if a reader can tell what was produced and
whether it still matches. The manifest records, per figure, its source, the
render parameters and the resulting PNG's size and SHA-256. `verify_manifest`
re-hashes the files and reports drift, so a stale or hand-edited image is caught
instead of shipped.

Public API:
    RenderRecord      - one produced figure
    ShotManifest      - the whole run (browser, figures, generated time)
    write_manifest(records, path, ...) -> ShotManifest
    read_manifest(path) -> ShotManifest
    verify_manifest(manifest, *, root=None) -> list[str]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentic_bi.shots.shots_types import ShotPlan

_CHUNK = 1 << 20


def sha256_file(path: str | Path) -> str:
    """The lowercase hex SHA-256 of a file (streamed, so size is irrelevant)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RenderRecord:
    """One figure produced by a run.

    Attributes:
        name: the figure's logical id.
        kind: ``html`` or ``terminal``.
        source: the source file the figure was rendered from.
        png: the output PNG path (as written).
        width: CSS viewport width.
        height: CSS viewport height.
        scale: device scale factor.
        sha256: the PNG's content hash.
        bytes: the PNG's size on disk.
    """

    name: str
    kind: str
    source: str
    png: str
    width: int
    height: int
    scale: float
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the record."""
        return {
            "name": self.name,
            "kind": self.kind,
            "source": self.source,
            "png": self.png,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderRecord:
        """Rebuild a record from its JSON view.

        Raises:
            ValueError: when `data` is not a mapping or a required field is
                missing or has the wrong type. A hand-edited or truncated
                manifest is a bad *input*, so it must reach the CLI as a
                `ValueError` (exit code 2), not as an unhandled `KeyError`.
        """
        if not isinstance(data, dict):
            raise ValueError("manifest: each figure must be a mapping")
        fields = (
            "name",
            "kind",
            "source",
            "png",
            "width",
            "height",
            "scale",
            "sha256",
            "bytes",
        )
        missing = [key for key in fields if key not in data]
        if missing:
            where = f" ({data.get('name')!r})" if data.get("name") else ""
            raise ValueError(f"manifest: figure is missing field(s) {missing}{where}")
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                source=str(data["source"]),
                png=str(data["png"]),
                width=int(data["width"]),
                height=int(data["height"]),
                scale=float(data["scale"]),
                sha256=str(data["sha256"]),
                bytes=int(data["bytes"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"manifest: figure {data.get('name')!r} has a bad field value: {exc}"
            ) from exc


@dataclass
class ShotManifest:
    """The whole run: which browser, which figures, when.

    Attributes:
        browser: the browser executable that was used.
        generated: the ISO-8601 UTC timestamp of the run.
        figures: the produced figures, in render order.
        plan: the plan file the run came from, when known.
    """

    browser: str
    generated: str
    figures: list[RenderRecord] = field(default_factory=list)
    plan: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the manifest."""
        return {
            "browser": self.browser,
            "generated": self.generated,
            "plan": self.plan,
            "figures": [f.to_dict() for f in self.figures],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShotManifest:
        """Rebuild a manifest from its JSON view."""
        return cls(
            browser=str(data.get("browser") or ""),
            generated=str(data.get("generated") or ""),
            plan=str(data.get("plan") or ""),
            figures=[RenderRecord.from_dict(f) for f in data.get("figures") or []],
        )


def write_manifest(
    records: list[RenderRecord],
    path: str | Path,
    *,
    browser: str,
    plan: str = "",
) -> ShotManifest:
    """Write a manifest JSON and return it.

    Args:
        records: the produced figures.
        path: where to write the manifest JSON.
        browser: the browser executable used.
        plan: the source plan file, when known.

    Returns:
        The written `ShotManifest`.
    """
    manifest = ShotManifest(
        browser=browser,
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        figures=list(records),
        plan=plan,
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def read_manifest(path: str | Path) -> ShotManifest:
    """Read a manifest JSON back into a `ShotManifest`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest: top level must be a mapping")
    return ShotManifest.from_dict(data)


def verify_manifest(
    manifest: ShotManifest,
    *,
    root: str | Path | None = None,
    plan: ShotPlan | None = None,
) -> list[str]:
    """Check every figure's file exists and still hashes to its recorded value.

    Args:
        manifest: the manifest to check.
        root: an optional base directory the recorded PNG paths are relative to;
            when omitted, the recorded paths are used as-is.
        plan: the plan the set should cover; when given, a figure named in the
            plan but absent from the manifest is reported as a problem. Without
            it the manifest is checked only against itself, so a run that built
            fewer figures than the plan asks for (``--only``, ``--no-strict``)
            would otherwise pass unnoticed.

    Returns:
        A list of human-readable problems; empty means the set is intact.
    """
    base = Path(root) if root is not None else None
    problems: list[str] = []
    for figure in manifest.figures:
        png = Path(figure.png)
        resolved = (base / png) if (base and not png.is_absolute()) else png
        if not resolved.exists():
            problems.append(f"{figure.name}: missing file {resolved}")
            continue
        actual = sha256_file(resolved)
        if actual != figure.sha256:
            problems.append(
                f"{figure.name}: hash mismatch (expected {figure.sha256[:12]}, "
                f"got {actual[:12]})"
            )
    if plan is not None:
        recorded = {figure.name for figure in manifest.figures}
        for spec in plan.figures:
            if spec.name not in recorded:
                problems.append(
                    f"{spec.name}: in the plan but not in the manifest "
                    f"({len(manifest.figures)} of {len(plan.figures)} figures built)"
                )
    return problems


__all__ = [
    "RenderRecord",
    "ShotManifest",
    "read_manifest",
    "sha256_file",
    "verify_manifest",
    "write_manifest",
]
