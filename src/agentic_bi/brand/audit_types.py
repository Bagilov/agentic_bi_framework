"""Result types for the document brand audit."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

_LEVEL_RANK = {"error": 3, "warning": 2, "info": 1, "off": 0}


@dataclass
class AuditFinding:
    """A single brand-book non-compliance."""

    rule_id: str
    level: str  # error | warning | info
    category: str  # color | font | background | element
    location: str  # e.g. 'slide 3 / shape "Title 1" / run 0'
    message: str
    value: str = ""  # the actual value (hex/font/...)
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditReport:
    """The document audit result."""

    path: str = ""
    findings: list[AuditFinding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.level == "warning"]

    def ok(self) -> bool:
        return not self.errors

    def by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.category] = out.get(f.category, 0) + 1
        return out

    def by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return out

    def add(self, f: AuditFinding) -> None:
        self.findings.append(f)

    def to_json(self, path: str | Path | None = None) -> str:
        payload = {
            "path": self.path,
            "summary": {
                "total": len(self.findings),
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "by_category": self.by_category(),
                "by_rule": self.by_rule(),
                "document": self.stats,
            },
            "theme_colors": self.theme,
            "findings": [f.as_dict() for f in self.findings],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def format(self, max_findings: int = 0) -> str:
        if not self.findings:
            return f"OK: {self.path} - no non-compliances found."
        info = len([f for f in self.findings if f.level == "info"])
        summary = (
            f"  total: {len(self.findings)} (error={len(self.errors)}, "
            f"warning={len(self.warnings)}, info={info})"
        )
        lines = [
            f"Audit: {self.path}",
            summary,
            f"  by category: {self.by_category()}",
            f"  by rule: {self.by_rule()}",
            "",
        ]
        shown = self.findings[:max_findings] if max_findings else self.findings
        for f in shown:
            lines.append(f"  [{f.level.upper():7}] {f.rule_id} @ {f.location}")
            lines.append(f"            {f.message}")
            if f.value:
                lines.append(f"            value: {f.value}")
        if max_findings and len(self.findings) > max_findings:
            lines.append(f"  ... {len(self.findings) - max_findings} more")
        return "\n".join(lines)


__all__ = ["AuditFinding", "AuditReport"]
