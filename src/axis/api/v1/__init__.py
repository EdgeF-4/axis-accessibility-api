"""API v1 — versioned HTTP surface.

The combined router is exported by :mod:`axis.api.v1.router`; that is what
:func:`axis.main.create_app` mounts under ``/api/v1``.
"""

from __future__ import annotations

from axis.api.v1.router import router

__all__ = ["router"]
