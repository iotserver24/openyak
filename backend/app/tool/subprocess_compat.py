"""Cross-platform subprocess helpers.

Centralises platform detection, shell selection, encoding handling,
and creationflags so individual tools don't duplicate this logic.
"""

from __future__ import annotations

import locale
import os
import shutil
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"


def get_subprocess_kwargs() -> dict[str, Any]:
    """Return platform-specific kwargs for subprocess.run().

    On Windows: includes ``creationflags=CREATE_NO_WINDOW``.
    On other platforms: returns an empty dict (no ``creationflags`` kwarg).
    """
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_bash_on_windows() -> str | None:
    """Find a bash executable on Windows (e.g. Git Bash).

    Returns the path to ``bash.exe`` if found, or ``None``.
    Checks:
      1. ``shutil.which("bash")`` — finds bash on PATH.
      2. Common Git for Windows location.
    """
    if not IS_WINDOWS:
        return None

    bash = shutil.which("bash")
    if bash:
        return bash

    # Common Git for Windows install path
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    if os.path.isfile(git_bash):
        return git_bash

    return None


def decode_subprocess_output(data: bytes) -> str:
    """Decode subprocess stdout/stderr with platform-aware fallback.

    Strategy:
      1. Try UTF-8 (strict) — works for bash / modern tools.
      2. On Windows only: try the system code page (e.g. CP936, CP1252).
      3. Fall back to UTF-8 with ``errors='replace'``.
    """
    # Try UTF-8 first (most common for modern tools)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # On Windows, try system code page
    if IS_WINDOWS:
        try:
            system_encoding = locale.getpreferredencoding(False)
            if system_encoding and system_encoding.lower().replace("-", "") != "utf8":
                return data.decode(system_encoding)
        except (UnicodeDecodeError, LookupError):
            pass

    # Final fallback
    return data.decode("utf-8", errors="replace")
