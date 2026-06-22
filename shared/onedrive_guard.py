"""OneDrive safety utilities — prevents saving production files to synced paths.

Used across all automation modules (InDesign, Photoshop, Illustrator, etc.)
to ensure InDesign documents, PSDs, AIs, and other large binary files are never
saved to OneDrive where sync corruption can occur.
"""
from __future__ import annotations

import os
import platform
import sys
import warnings
from pathlib import Path

_ONEDRIVE_MARKERS = ("OneDrive", "onedrive", "ONEDRIVE", "One Drive", "one drive")


def is_onedrive_path(p: str | Path) -> bool:
    """Return True if the path is inside a OneDrive-synced folder."""
    path_str = str(p)
    return any(marker in path_str for marker in _ONEDRIVE_MARKERS)


def get_safe_output_dir(app_name: str = "General") -> Path:
    """Return a safe local directory for output, never on OneDrive.

    Priority:
      1. PRODUCTION_OUTPUT_DIR env var (user override)
      2. C:\\Users\\<user>\\Production-Automation-Output\\<app_name> (Windows)
      3. ~/Production-Automation-Output/<app_name> (other OS)
    """
    env_override = os.environ.get("PRODUCTION_OUTPUT_DIR")
    if env_override:
        p = Path(env_override)
        if is_onedrive_path(p):
            warnings.warn(
                f"PRODUCTION_OUTPUT_DIR is on OneDrive ({p}). "
                "Using fallback local path instead."
            )
        else:
            output = p / app_name
            output.mkdir(parents=True, exist_ok=True)
            return output

    if platform.system() == "Windows":
        home = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default"))
    else:
        home = Path.home()

    output_dir = home / "Production-Automation-Output" / app_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def validate_output_path(target: str | Path, app_name: str = "General") -> str | None:
    """Validate that a target path is not on OneDrive.

    Returns error string if on OneDrive, None if safe.
    """
    if is_onedrive_path(target):
        safe = get_safe_output_dir(app_name)
        return (
            f"ERROR: Path is on OneDrive ({target}). "
            f"Sync corrupts production files. "
            f"Use a local path instead, e.g.: {safe}"
        )
    return None


def check_script_location():
    """Warn if the calling script is running from OneDrive."""
    import inspect
    caller = inspect.stack()[1]
    caller_file = caller.filename

    if is_onedrive_path(caller_file):
        username = os.environ.get("USERNAME", "user")
        print(
            f"WARNING: Running from OneDrive path:\n"
            f"  {caller_file}\n"
            f"Recommended: Move to C:\\Users\\{username}\\production-automation\\",
            file=sys.stderr,
        )
