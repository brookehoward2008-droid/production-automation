"""Windows COM bridge utilities for Adobe applications.

Provides connection helpers for InDesign, Photoshop, Illustrator via pywin32.
"""
from __future__ import annotations

import platform
from typing import Any

# Known COM PROGIDs for Adobe apps
ADOBE_PROGIDS = {
    "indesign": [
        "InDesign.Application",
        "InDesign.Application.CC.2024",
        "InDesign.Application.2024",
        "InDesign.Application.CC.2023",
        "InDesign.Application.2023",
        "InDesign.Application.CC.2022",
        "InDesign.Application.CC.2021",
    ],
    "photoshop": [
        "Photoshop.Application",
        "Photoshop.Application.2024",
        "Photoshop.Application.2023",
    ],
    "illustrator": [
        "Illustrator.Application",
        "Illustrator.Application.2024",
        "Illustrator.Application.CC.2024",
    ],
}


def connect_adobe_app(app_name: str) -> Any:
    """Connect to an Adobe application via COM.

    Args:
        app_name: One of 'indesign', 'photoshop', 'illustrator'

    Returns:
        The COM application object.

    Raises:
        RuntimeError: If not on Windows or app can't be reached.
    """
    if platform.system() != "Windows":
        raise RuntimeError(f"COM automation requires Windows. Current OS: {platform.system()}")

    import win32com.client

    progids = ADOBE_PROGIDS.get(app_name.lower())
    if not progids:
        raise ValueError(f"Unknown app: {app_name}. Available: {list(ADOBE_PROGIDS.keys())}")

    last_error = None
    for progid in progids:
        try:
            app = win32com.client.Dispatch(progid)
            return app
        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Could not connect to {app_name} via COM. Is it running? "
        f"Last error: {last_error}"
    )


def check_adobe_available(app_name: str) -> dict:
    """Check if an Adobe app is available via COM.

    Returns dict with 'available', 'app_name', 'error' keys.
    """
    try:
        app = connect_adobe_app(app_name)
        return {"available": True, "app_name": app_name, "version": str(getattr(app, "Version", "unknown"))}
    except Exception as e:
        return {"available": False, "app_name": app_name, "error": str(e)}
