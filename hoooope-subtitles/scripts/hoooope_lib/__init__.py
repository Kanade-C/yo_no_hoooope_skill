"""Shared helpers for the HOOOOPE subtitle CLI.

New modules live in this four-o package. During the migration, the legacy
three-o package directory remains on the import path so older extracted helpers
can be used without breaking production commands.
"""

from __future__ import annotations

from pathlib import Path

_LEGACY_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "hooope_lib"
if _LEGACY_PACKAGE_DIR.exists():
    __path__.append(str(_LEGACY_PACKAGE_DIR))  # type: ignore[name-defined]
