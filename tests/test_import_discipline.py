"""Import & enforcement discipline checks.

These tests fail the build if the codebase grows a forbidden shape that
the architecture explicitly rules out:

* Authorization decisions must flow through ``require_scope`` (a single
  enforcement point). Scattering ``if principal.scopes`` or
  ``if user.is_admin`` checks defeats the contract.
* The Anthropic SDK is allowed only in :mod:`axis.extraction.*` (added
  in Phase 4) — this test is forward-compatible.
* The framework-free :mod:`axis.domain` must not import FastAPI or
  SQLAlchemy.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "axis"


def _python_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# Scope enforcement must live behind require_scope() only.
# ---------------------------------------------------------------------------

_FORBIDDEN_SCOPE_PATTERN = re.compile(
    r"\bif\s+[^\n]*\.(scopes|is_admin)\b",
    re.MULTILINE,
)


def test_no_inline_scope_checks_outside_auth_or_deps() -> None:
    allowed = {
        SRC / "auth" / "principal.py",  # has_scope() method
        SRC / "auth" / "rbac.py",
        SRC / "api" / "v1" / "deps.py",
    }
    bad: list[str] = []
    for path in _python_files():
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN_SCOPE_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            bad.append(f"{path.relative_to(SRC.parent.parent)}:{line_no}: {match.group(0)}")
    assert not bad, (
        "Authorization decisions must use require_scope(). Inline checks found:\n" + "\n".join(bad)
    )


# ---------------------------------------------------------------------------
# Anthropic SDK is locked to the extraction adapter.
# ---------------------------------------------------------------------------


def test_anthropic_import_only_in_extraction() -> None:
    allowed_prefix = str((SRC / "extraction").resolve())
    bad: list[str] = []
    pattern = re.compile(r"^\s*(?:from\s+anthropic|import\s+anthropic)\b", re.MULTILINE)
    for path in _python_files():
        if str(path.resolve()).startswith(allowed_prefix):
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            bad.append(str(path.relative_to(SRC.parent.parent)))
    assert not bad, "Anthropic SDK is restricted to axis.extraction.*. Found in:\n  " + "\n  ".join(
        bad
    )


# ---------------------------------------------------------------------------
# Domain layer is framework-free.
# ---------------------------------------------------------------------------


def test_domain_is_framework_free() -> None:
    domain_files = list((SRC / "domain").rglob("*.py"))
    forbidden = (
        re.compile(r"^\s*from\s+fastapi\b", re.MULTILINE),
        re.compile(r"^\s*from\s+sqlalchemy\b", re.MULTILINE),
        re.compile(r"^\s*import\s+fastapi\b", re.MULTILINE),
        re.compile(r"^\s*import\s+sqlalchemy\b", re.MULTILINE),
    )
    bad: list[str] = []
    for path in domain_files:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                bad.append(f"{path.relative_to(SRC.parent.parent)}: {pattern.pattern}")
    assert not bad, "axis.domain must not import FastAPI or SQLAlchemy:\n  " + "\n  ".join(bad)
