from __future__ import annotations

"""Compatibility bridge for POWERHOUSE AI V74.3.

Render may continue to start ``uvicorn v74_app:app``. Configure the complete
India index command set before importing V74.3 so NIFTY, BANKNIFTY,
MIDCPNIFTY and SENSEX are first-class defaults while preserving legacy APIs.
"""

import os

os.environ.setdefault("V74_AUTO_INDEX_CODES", "NIFTY,BANKNIFTY,MIDCPNIFTY,SENSEX")

from v743_app import app  # noqa: E402,F401
