"""Release metadata exposed by the running AuthHub process."""

from __future__ import annotations

import os
from typing import Dict


VERSION = "0.5.3"


def runtime_release() -> Dict[str, str]:
    """Return deployment metadata without relying on cached static assets."""
    version = os.getenv("AUTH_HUB_RELEASE", VERSION).strip() or VERSION
    build = os.getenv("AUTH_HUB_BUILD", "local").strip() or "local"
    return {"version": version, "build": build}
