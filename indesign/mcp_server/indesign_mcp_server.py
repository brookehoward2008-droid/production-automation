"""InDesign MCP Server — exposes InDesign automation as MCP tools for Claude Code.

Runs on Windows with Adobe InDesign installed. Communicates via stdio (MCP protocol).
Claude Code spawns this as a subprocess and calls tools to control InDesign.

Requirements:
    pip install mcp pywin32

Registration (add to ~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "indesign": {
          "command": "python",
          "args": ["C:/path/to/theory-of-sigh/scripts/indesign_mcp_server.py"]
        }
      }
    }

Usage:
    python scripts/indesign_mcp_server.py
"""
from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
import warnings
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# OneDrive safety check
# ---------------------------------------------------------------------------

_ONEDRIVE_MARKERS = ("OneDrive", "onedrive", "ONEDRIVE")


def _is_onedrive_path(p: Path) -> bool:
    """Return True if the path is inside a OneDrive-synced folder."""
    parts_str = str(p)
    return any(marker in parts_str for marker in _ONEDRIVE_MARKERS)


def _get_safe_output_dir() -> Path:
    """Return a safe local directory for InDesign output, never on OneDrive.

    Priority:
      1. INDESIGN_OUTPUT_DIR env var (user override)
      2. C:\\Users\\<user>\\InDesign-Automation-Output (Windows)
      3. ~/InDesign-Automation-Output (other OS)
    """
    env_override = os.environ.get("INDESIGN_OUTPUT_DIR")
    if env_override:
        p = Path(env_override)
        if _is_onedrive_path(p):
            warnings.warn(
                f"INDESIGN_OUTPUT_DIR is on OneDrive ({p}). "
                "OneDrive sync can corrupt InDesign files. "
                "Using fallback local path instead."
            )
        else:
            p.mkdir(parents=True, exist_ok=True)
            return p

    if platform.system() == "Windows":
        home = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default"))
    else:
        home = Path.home()

    output_dir = home / "InDesign-Automation-Output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _check_server_location():
    """Warn at startup if the server itself is running from OneDrive."""
    server_path = Path(__file__).resolve()
    if _is_onedrive_path(server_path):
        msg = (
            f"WARNING: This MCP server is running from a OneDrive path:\n"
            f"  {server_path}\n"
            f"OneDrive file sync can cause locking issues with InDesign COM.\n"
            f"Recommended: Move this folder to a local path like:\n"
            f"  C:\\Users\\{os.environ.get('USERNAME', 'user')}\\indesign-mcp-server\\"
        )
        print(msg, file=sys.stderr)


# Run the check on import
_check_server_location()

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "InDesign Automation",
    version="1.0.0",
)

ROOT = Path(__file__).resolve().parents[1]
SAFE_OUTPUT_DIR = _get_safe_output_dir()

# ---------------------------------------------------------------------------
# COM connection helpers (Windows only)
# ---------------------------------------------------------------------------

PROGIDS = [
    "InDesign.Application",
    "InDesign.Application.CC.2024",
    "InDesign.Application.2024",
    "InDesign.Application.CC.2023",
    "InDesign.Application.2023",
    "InDesign.Application.CC.2022",
    "InDesign.Application.CC.2021",
]

# ExtendScript language constant
JAVASCRIPT = 1246973031
NEVER_INTERACT = 1699640946

_indesign_app = None


def _get_indesign():
    """Connect to InDesign via COM. Caches the connection."""
    global _indesign_app
    if _indesign_app is not None:
        try:
            _ = _indesign_app.Name
            return _indesign_app
        except Exception:
            _indesign_app = None

    if platform.system() != "Windows":
        raise RuntimeError(
            "InDesign COM automation requires Windows. "
            f"Current OS: {platform.system()}"
        )

    import win32com.client as win32

    last_error = None
    for progid in PROGIDS:
        try:
            app = win32.Dispatch(progid)
            _indesign_app = app
            return app
        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        "Could not connect to InDesign over COM. Is InDesign installed and "
        f"licensed? Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def run_jsx(script: str) -> str:
    """Execute an ExtendScript (JavaScript) snippet in InDesign and return the result.

    Use this to run arbitrary InDesign scripting commands. The script runs
    in InDesign's ExtendScript engine with full access to the InDesign DOM.

    Args:
        script: ExtendScript/JavaScript code to execute in InDesign.

    Returns:
        The string result of the script execution, or error message.
    """
    app = _get_indesign()
    try:
        app.ScriptPreferences.UserInteractionLevel = NEVER_INTERACT
    except Exception:
        pass

    try:
        result = app.DoScript(script, JAVASCRIPT)
        return str(result) if result else "Script executed successfully (no return value)."
    except Exception as exc:
        return f"ERROR: {exc}"


@mcp.tool()
def run_jsx_file(file_path: str) -> str:
    """Execute a .jsx file in InDesign.

    Args:
        file_path: Absolute path to the .jsx file to execute.

    Returns:
        Result of execution or error message.
    """
    path = Path(file_path)
    if not path.exists():
        return f"ERROR: File not found: {file_path}"
    if not path.suffix.lower() == ".jsx":
        return f"ERROR: Expected .jsx file, got: {path.suffix}"

    app = _get_indesign()
    try:
        app.ScriptPreferences.UserInteractionLevel = NEVER_INTERACT
    except Exception:
        pass

    try:
        result = app.DoScript(str(path), JAVASCRIPT)
        return str(result) if result else f"Script {path.name} executed successfully."
    except Exception as exc:
        return f"ERROR running {path.name}: {exc}"


@mcp.tool()
def build_handoff(handoff_dir: str) -> str:
    """Generate the InDesign JSX from a handoff package and execute it.

    Reads the production manifest and layout instructions, generates the
    ExtendScript, then runs it in InDesign to build the full 50-page document.

    Args:
        handoff_dir: Path to the handoff package directory containing
                     master_production_manifest.json, production_layout_instructions.csv,
                     and assets/ subfolder.

    Returns:
        Build status and output file paths.
    """
    handoff_path = Path(handoff_dir).resolve()
    if not handoff_path.is_dir():
        return f"ERROR: Not a directory: {handoff_dir}"
    if not (handoff_path / "master_production_manifest.json").exists():
        return f"ERROR: No master_production_manifest.json in {handoff_dir}"

    # Add scripts to path
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_from_handoff

    try:
        jsx_path = build_from_handoff.generate_handoff_jsx(handoff_path)
    except Exception as exc:
        return f"ERROR generating JSX: {exc}"

    # Now execute the JSX in InDesign
    app = _get_indesign()
    try:
        app.ScriptPreferences.UserInteractionLevel = NEVER_INTERACT
    except Exception:
        pass

    start = time.time()
    try:
        app.DoScript(str(jsx_path), JAVASCRIPT)
    except Exception as exc:
        return f"JSX generated at {jsx_path} but InDesign execution failed: {exc}"

    elapsed = time.time() - start
    indd = ROOT / "visceral-production-route" / "output" / "indesign" / "the-visceral-theory-of-sight-50pp-handoff.indd"
    pdf = ROOT / "visceral-production-route" / "output" / "pdf" / "the-visceral-theory-of-sight-50pp-handoff.pdf"

    return (
        f"Build complete in {elapsed:.1f}s.\n"
        f"INDD: {indd} (exists: {indd.exists()})\n"
        f"PDF: {pdf} (exists: {pdf.exists()})\n"
        f"JSX: {jsx_path}"
    )


@mcp.tool()
def get_document_info() -> str:
    """Get information about the currently active InDesign document.

    Returns:
        JSON with document name, page count, dimensions, links status, etc.
    """
    app = _get_indesign()
    if app.Documents.Count == 0:
        return "No documents open in InDesign."

    doc = app.ActiveDocument
    try:
        info = {
            "name": doc.Name,
            "full_path": doc.FullName if doc.Saved else "(unsaved)",
            "page_count": doc.Pages.Count,
            "page_width": str(doc.DocumentPreferences.PageWidth),
            "page_height": str(doc.DocumentPreferences.PageHeight),
            "facing_pages": doc.DocumentPreferences.FacingPages,
            "total_links": doc.Links.Count,
            "text_frames": doc.TextFrames.Count,
        }

        # Count missing links
        missing = 0
        for i in range(1, doc.Links.Count + 1):
            try:
                if doc.Links.Item(i).Status == 0x6C6E6B4D:  # LINK_MISSING
                    missing += 1
            except Exception:
                pass
        info["missing_links"] = missing

        # Count overset frames
        overset = 0
        for i in range(1, doc.TextFrames.Count + 1):
            try:
                if doc.TextFrames.Item(i).Overflows:
                    overset += 1
            except Exception:
                pass
        info["overset_text_frames"] = overset

        return json.dumps(info, indent=2)
    except Exception as exc:
        return f"ERROR reading document info: {exc}"


@mcp.tool()
def export_pdf(output_path: str = "", preset: str = "[High Quality Print]") -> str:
    """Export the active InDesign document to PDF.

    Args:
        output_path: Where to save the PDF. If empty, saves to safe local directory (never OneDrive).
        preset: PDF export preset name (default: "[High Quality Print]").

    Returns:
        Path to the exported PDF or error message.
    """
    app = _get_indesign()
    if app.Documents.Count == 0:
        return "ERROR: No documents open in InDesign."

    doc = app.ActiveDocument

    if output_path and _is_onedrive_path(Path(output_path)):
        return (
            f"ERROR: Output path is on OneDrive ({output_path}). "
            f"OneDrive sync corrupts InDesign files. "
            f"Use a local path instead, e.g.: {SAFE_OUTPUT_DIR / 'export.pdf'}"
        )

    if not output_path:
        if doc.Saved and not _is_onedrive_path(Path(doc.FullName)):
            output_path = str(Path(doc.FullName).with_suffix(".pdf"))
        else:
            output_path = str(SAFE_OUTPUT_DIR / f"{doc.Name.replace('.indd', '')}.pdf")

    script = f"""
    var doc = app.activeDocument;
    var pdfFile = File({json.dumps(output_path)});
    if (!pdfFile.parent.exists) pdfFile.parent.create();
    var preset = null;
    try {{
        preset = app.pdfExportPresets.itemByName({json.dumps(preset)});
        preset.name;
    }} catch (e) {{
        preset = app.pdfExportPresets.item(0);
    }}
    doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false, preset);
    pdfFile.fsName;
    """
    result = run_jsx(script)
    return f"PDF exported: {result}"


@mcp.tool()
def place_image(page_number: int, x: float, y: float, width: float, height: float, image_path: str) -> str:
    """Place an image on a specific page at given coordinates.

    All measurements are in millimeters relative to the page trim.

    Args:
        page_number: 1-based page number.
        x: Left position in mm from page trim edge.
        y: Top position in mm from page trim edge.
        width: Frame width in mm.
        height: Frame height in mm.
        image_path: Absolute path to the image file.

    Returns:
        Confirmation or error message.
    """
    script = f"""
    var doc = app.activeDocument;
    var page = doc.pages.item({page_number - 1});
    var rect = page.rectangles.add();
    var pb = page.bounds;
    rect.geometricBounds = [
        (Number(pb[0]) + {y}) + "mm",
        (Number(pb[1]) + {x}) + "mm",
        (Number(pb[0]) + {y + height}) + "mm",
        (Number(pb[1]) + {x + width}) + "mm"
    ];
    rect.strokeWeight = 0;
    try {{
        rect.place(File({json.dumps(image_path)}));
        rect.fit(FitOptions.FILL_PROPORTIONALLY);
        rect.fit(FitOptions.CENTER_CONTENT);
        "Image placed on page {page_number} at ({x}, {y}) mm";
    }} catch (e) {{
        "ERROR: " + e.message;
    }}
    """
    return run_jsx(script)


@mcp.tool()
def add_text_frame(page_number: int, x: float, y: float, width: float, height: float, text: str, font_size: float = 10.0, font_style: str = "Regular") -> str:
    """Add a text frame to a specific page.

    All measurements in mm relative to page trim.

    Args:
        page_number: 1-based page number.
        x: Left position in mm.
        y: Top position in mm.
        width: Frame width in mm.
        height: Frame height in mm.
        text: The text content to place.
        font_size: Point size (default 10).
        font_style: Font style like "Regular", "Bold", "Italic" (default "Regular").

    Returns:
        Confirmation or error message.
    """
    escaped_text = json.dumps(text)
    script = f"""
    var doc = app.activeDocument;
    var page = doc.pages.item({page_number - 1});
    var tf = page.textFrames.add();
    var pb = page.bounds;
    tf.geometricBounds = [
        (Number(pb[0]) + {y}) + "mm",
        (Number(pb[1]) + {x}) + "mm",
        (Number(pb[0]) + {y + height}) + "mm",
        (Number(pb[1]) + {x + width}) + "mm"
    ];
    tf.contents = {escaped_text};
    try {{
        tf.textFramePreferences.insetSpacing = ["2mm", "2mm", "2mm", "2mm"];
        tf.texts[0].appliedFont = app.fonts.item("Helvetica");
        tf.texts[0].fontStyle = {json.dumps(font_style)};
        tf.texts[0].pointSize = {font_size};
        tf.texts[0].leading = {font_size * 1.22};
    }} catch (e) {{}}
    "Text frame added on page {page_number}";
    """
    return run_jsx(script)


@mcp.tool()
def list_pages() -> str:
    """List all pages in the active document with basic info.

    Returns:
        JSON array of page info (number, bounds, item counts).
    """
    script = """
    var doc = app.activeDocument;
    var result = [];
    for (var i = 0; i < doc.pages.length; i++) {
        var p = doc.pages[i];
        result.push({
            number: i + 1,
            name: p.name,
            bounds: p.bounds.toString(),
            rectangles: p.rectangles.length,
            textFrames: p.textFrames.length
        });
    }
    JSON.stringify(result);
    """
    return run_jsx(script)


@mcp.tool()
def new_document(width_mm: float = 279.4, height_mm: float = 215.9, pages: int = 1, facing_pages: bool = True, bleed_mm: float = 3.175) -> str:
    """Create a new InDesign document.

    Args:
        width_mm: Page width in mm (default: 279.4 = US Letter landscape).
        height_mm: Page height in mm (default: 215.9).
        pages: Number of pages (default: 1).
        facing_pages: Whether to use facing pages (default: True).
        bleed_mm: Bleed on all sides in mm (default: 3.175 = 0.125in).

    Returns:
        Confirmation with document details.
    """
    script = f"""
    var doc = app.documents.add();
    doc.documentPreferences.pageWidth = "{width_mm}mm";
    doc.documentPreferences.pageHeight = "{height_mm}mm";
    doc.documentPreferences.facingPages = {str(facing_pages).lower()};
    doc.documentPreferences.pagesPerDocument = {pages};
    doc.documentPreferences.documentBleedTopOffset = "{bleed_mm}mm";
    doc.documentPreferences.documentBleedBottomOffset = "{bleed_mm}mm";
    doc.documentPreferences.documentBleedInsideOrLeftOffset = "{bleed_mm}mm";
    doc.documentPreferences.documentBleedOutsideOrRightOffset = "{bleed_mm}mm";
    "Created " + doc.pages.length + "-page document (" + "{width_mm}mm x {height_mm}mm)";
    """
    return run_jsx(script)


@mcp.tool()
def save_document(file_path: str = "") -> str:
    """Save the active InDesign document.

    Args:
        file_path: Path to save as. If empty, saves to current location (must already be saved once).
                   Will reject OneDrive paths to prevent sync corruption.

    Returns:
        Save confirmation or error.
    """
    if file_path and _is_onedrive_path(Path(file_path)):
        return (
            f"ERROR: Cannot save to OneDrive path ({file_path}). "
            f"OneDrive sync corrupts InDesign files. "
            f"Use a local path instead, e.g.: {SAFE_OUTPUT_DIR / 'document.indd'}"
        )
    if file_path:
        script = f"""
        var doc = app.activeDocument;
        var f = File({json.dumps(file_path)});
        if (!f.parent.exists) f.parent.create();
        doc.save(f);
        "Saved to: " + f.fsName;
        """
    else:
        script = """
        var doc = app.activeDocument;
        doc.save();
        "Saved: " + doc.fullName;
        """
    return run_jsx(script)


@mcp.tool()
def close_document(save: bool = True) -> str:
    """Close the active InDesign document.

    Args:
        save: Whether to save before closing (default: True).

    Returns:
        Confirmation message.
    """
    save_opt = "SaveOptions.YES" if save else "SaveOptions.NO"
    script = f"""
    var doc = app.activeDocument;
    var name = doc.name;
    doc.close({save_opt});
    "Closed: " + name;
    """
    return run_jsx(script)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
