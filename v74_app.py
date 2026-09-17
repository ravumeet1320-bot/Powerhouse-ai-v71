from __future__ import annotations

"""Compatibility bridge: Render may still start uvicorn v74_app:app.
This file intentionally exposes the V74.3 application while the preserved V74.2
wrapper lives in v742_app.py for backwards-compatible imports.
"""

from v743_app import app  # noqa: F401

