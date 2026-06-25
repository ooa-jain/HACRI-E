"""
Pytest config for the HACRI-E2 web app.

Boots TestClient / AsyncClient with a mongomock-motor fake so tests run
without a real Mongo. Also patches matplotlib to use the headless Agg
backend so tests don't need a display.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Headless matplotlib
import matplotlib  # noqa: E402

matplotlib.use("Agg")

# Required env vars for settings
os.environ.setdefault("MONGODB_URI", "mongodb://mock")
os.environ.setdefault("MONGODB_DB", "hacri_e2_test")
os.environ.setdefault("SESSION_SECRET", "test-secret-test-secret-test-secret")

# Tests don't need to send real emails.
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("EMAIL_FROM", "")

# Default to "no email" so the emailer is a no-op in tests
from app import emailer  # noqa: E402

emailer.SMTP_ENABLED = False