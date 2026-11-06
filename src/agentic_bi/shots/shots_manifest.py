"""Manifest of a rendered figure set: statuses, sizes, hashes and verification.

A figure set is only trustworthy if a reader can tell what was requested, what
was produced, and whether it still matches. The manifest records, per figure,
its source, the render parameters and what happened to it (`ok`, `skipped`,
`failed`); an `ok` figure also carries the PNG's size, SHA-256 and byte count.
`verify_manifest` re-hashes the files, reports drift and reports figures that
were never built, so a stale or hand-edited image is caught instead of shipped.

The on-disk form (deterministic JSON, no timestamps, no absolute paths) is
written by `shots_store`.

Public API:
    STATUS_OK, STATUS_SKIPPED, STATUS_FAILED
    RenderRecord      - one requested figure and what happened to it
    ShotManifest      - the whole run (browser name, figures, plan)
    sha256_file(path) -> str
    verify_manifest(manifest, ...) -> list[str]
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_bi.shots.shots_types import ShotPlan

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUSES = frozenset({STATUS_OK, STATUS_SKIPPED, STATUS_FAILED})

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
    """One requested figure and what the run did with it.

    Attributes:
        name: the figure's logical id.
        kind: ``html`` or ``terminal``.
        source: the source file name the figure was rendered from.
        png: the output PNG file name (relative to the manifest), empty when the
            figure was not produced.
        width: CSS viewport width.
        height: CSS viewport height.
        scale: device scale factor.
        sha256: the PNG's content hash (empty when not produced).
        bytes: the PNG's size on disk (0 when not produced).
        status: ``ok``, ``skipped`` or ``failed``.
        reason: why a figure was skipped or failed; empty for ``ok``.
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
    status: str = STATUS_OK
    reason: str = ""

    @property
    def built(self) -> bool:
        """Whether this figure's PNG was actually produced."""
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the record (stable key order)."""
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
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
        status = data.get("status") or STATUS_OK
        where = f" ({data.get('name')!r})" if data.get("name") else ""
        if status not in STATUSES:
            raise ValueError(
                f"manifest: figure has an unknown status{where}: {status!r}"
            )
        required = ["name", "kind", "source"]
        if status == STATUS_OK:
            required += ["png", "width", "height", "scale", "sha256", "bytes"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"manifest: figure is missing field(s) {missing}{where}")
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                source=str(data["source"]),
                png=str(data.get("png") or ""),
                width=int(data.get("width") or 0),
                height=int(data.get("height") or 0),
                scale=float(data.get("scale") or 0.0),
                sha256=str(data.get("sha256") or ""),
                bytes=int(data.get("bytes") or 0),
                status=str(status),
                reason=str(data.get("reason") or ""),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"manifest: figure {data.get('name')!r} has a bad field value: {exc}"
            ) from exc


@dataclass
class ShotManifest:
    """The whole run: which browser, which figures, from which plan.

    Attributes:
        browser: the browser executable name (never a full path, so the manifest
            does not depend on where the browser is installed).
        generated: an optional ISO-8601 timestamp; empty by default so two runs
            of the same input produce byte-identical manifests.
        figures: the requested figures, in plan order, whatever their status.
        plan: the plan file name the run came from, when known.
        root: the directory relative PNG paths resolve against (not serialized;
            filled by `read_manifest`/`write_manifest`).
    """

    browser: str
    generated: str = ""
    figures: list[RenderRecord] = field(default_factory=list)
    plan: str = ""
    root: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the manifest (stable key order)."""
        return {
            "browser": self.browser,
            "generated": self.generated,
            "plan": self.plan,
            "figures": [f.to_dict() for f in self.figures],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShotManifest:
        """Rebuild a manifest from its JSON view."""
        if not isinstance(data, dict):
            raise ValueError("manifest: top level must be a mapping")
        raw = data.get("figures")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise ValueError("manifest: 'figures' must be a list")
        return cls(
            browser=str(data.get("browser") or ""),
            generated=str(data.get("generated") or ""),
            plan=str(data.get("plan") or ""),
            figures=[RenderRecord.from_dict(f) for f in raw],
        )


def verify_manifest(
    manifest: ShotManifest,
    *,
    root: str | Path | None = None,
    plan: ShotPlan | None = None,
) -> list[str]:
    """Check every figure's status, file and hash.

    Args:
        manifest: the manifest to check.
        root: an optional base directory the recorded PNG paths are relative to;
            when omitted, `manifest.root` (the manifest's own directory) is used,
            then the paths are used as-is. Each figure is checked by hash **and**
            by the recorded `bytes`, so a manifest whose size no longer matches
            the file is drift, not a match.
        plan: the plan the set should cover; when given, a figure named in the
            plan but absent from the manifest is reported as a problem. Without
            it the manifest is checked only against itself, so a run that built
            fewer figures than the plan asks for (``--only``, ``--no-strict``)
            would otherwise pass unnoticed.

    Returns:
        A list of human-readable problems; empty means the set is intact.
    """
    base = Path(root) if root is not None else None
    if base is None and manifest.root:
        base = Path(manifest.root)
    problems: list[str] = []
    for figure in manifest.figures:
        if not figure.built:
            problems.append(
                f"{figure.name}: not built ({figure.status}: "
                f"{figure.reason or 'no reason recorded'})"
            )
            continue
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
            continue
        # The recorded size is part of the manifest contract and was never
        # re-checked, so a manifest with a wrong `bytes` value verified clean.
        size = resolved.stat().st_size
        if figure.bytes and size != figure.bytes:
            problems.append(
                f"{figure.name}: size mismatch (expected {figure.bytes}, got {size})"
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
    "STATUSES",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "RenderRecord",
    "ShotManifest",
    "sha256_file",
    "verify_manifest",
]
