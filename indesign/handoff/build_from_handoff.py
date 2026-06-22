"""Generate an InDesign ExtendScript (JSX) from a production handoff package.

Reads the master_production_manifest.json and production_layout_instructions.csv
produced by the handoff extraction pipeline, then emits a self-contained .jsx that
recreates the 50-page US Letter landscape document in InDesign with exact image
placement, text frames, and K-only swatches.

Usage:
    python scripts/build_from_handoff.py /path/to/handoff_package

The handoff directory must contain:
    master_production_manifest.json
    production_layout_instructions.csv
    assets/  (73 PNG page extracts)

Outputs (under visceral-production-route/):
    templates/indesign-handoff-build.jsx
    reports/handoff-build-generator-report.json
    assets/handoff/  (copied PNGs ready for InDesign linking)
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from textwrap import dedent

try:
    from scripts import build_visceral_book as book
except ModuleNotFoundError:
    import build_visceral_book as book

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "visceral-production-route"
TEMPLATE_OUT = ROUTE / "templates"
REPORTS_OUT = ROUTE / "reports"
HANDOFF_ASSET_DIR = ROUTE / "assets" / "handoff"

# US Letter landscape with 0.125in bleed
TRIM_W_MM = 279.4
TRIM_H_MM = 215.9
BLEED_MM = 3.175

# Conversion constants
PT_TO_MM = 25.4 / 72.0
BLEED_PT = BLEED_MM / PT_TO_MM  # ~9pt


def _pt_to_trim_mm(pt_val: float) -> float:
    """Convert a bleed-inclusive point coordinate to trim-relative mm."""
    return (pt_val - BLEED_PT) * PT_TO_MM


def _parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse '(x0, y0, x1, y1)' string into a tuple of floats."""
    cleaned = bbox_str.strip("() ")
    parts = [float(x.strip()) for x in cleaned.split(",")]
    return (parts[0], parts[1], parts[2], parts[3])


def load_manifest(handoff_dir: Path) -> dict:
    manifest_path = handoff_dir / "master_production_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_csv_instructions(handoff_dir: Path) -> list[dict]:
    csv_path = handoff_dir / "production_layout_instructions.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def copy_handoff_assets(handoff_dir: Path) -> Path:
    """Copy handoff PNGs into the production route for InDesign linking."""
    src = handoff_dir / "assets"
    if not src.is_dir():
        raise FileNotFoundError(f"Assets directory not found: {src}")
    HANDOFF_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for png in sorted(src.glob("*.png")):
        dest = HANDOFF_ASSET_DIR / png.name
        shutil.copy2(png, dest)
        count += 1
    print(f"  Copied {count} handoff assets to {HANDOFF_ASSET_DIR}")
    return HANDOFF_ASSET_DIR


def _escape_jsx_string(s: str) -> str:
    """Escape a string for embedding in JSX source."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _build_page_data(manifest: dict, asset_dir: Path) -> list[dict]:
    """Transform manifest pages into JSX-ready data structures."""
    pages = []
    for page in manifest["pages"]:
        pn = page["page_number"]
        images = []
        for img in page["images"]:
            x0, y0, x1, y1 = _parse_bbox(img["bbox"])
            top_mm = _pt_to_trim_mm(y0)
            left_mm = _pt_to_trim_mm(x0)
            bottom_mm = _pt_to_trim_mm(y1)
            right_mm = _pt_to_trim_mm(x1)
            local_file = asset_dir / Path(img["local_path"]).name
            images.append({
                "bounds": [top_mm, left_mm, bottom_mm, right_mm],
                "path": local_file.as_posix(),
                "category": img["category"],
                "source_asset": img.get("source_asset", ""),
            })
        content = page.get("content", "")
        layout = page.get("layout_metadata", {})
        pages.append({
            "page_number": pn,
            "content": content,
            "images": images,
            "layout": layout,
        })
    return pages


def _generate_jsx(pages: list[dict], asset_dir: Path) -> str:
    """Generate the complete InDesign ExtendScript."""
    output_indd = (ROUTE / "output" / "indesign" / "the-visceral-theory-of-sight-50pp-handoff.indd").as_posix()
    output_idml = (ROUTE / "output" / "indesign" / "the-visceral-theory-of-sight-50pp-handoff.idml").as_posix()
    output_pdf = (ROUTE / "output" / "pdf" / "the-visceral-theory-of-sight-50pp-handoff.pdf").as_posix()
    output_report = (REPORTS_OUT / "handoff-build-indesign-report.json").as_posix()

    # Build PAGE_DATA array as JSON for embedding
    jsx_page_data = json.dumps(pages, indent=2)

    jsx = dedent(f"""\
    // The Visceral Theory of Sight - Handoff Package InDesign Builder
    // Generated from master_production_manifest.json
    // Run from InDesign: File > Scripts > Other Script...
    // Builds US Letter landscape facing pages, 0.125in bleed, K-only, exact placement from production manifest.

    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;

    try {{

    var OUTPUT_INDD = {json.dumps(output_indd)};
    var OUTPUT_IDML = {json.dumps(output_idml)};
    var OUTPUT_PDF = {json.dumps(output_pdf)};
    var OUTPUT_REPORT = {json.dumps(output_report)};

    var PAGE_DATA = {jsx_page_data};

    // --- Document setup ---
    function mm(v) {{ return v + "mm"; }}

    function setupDoc() {{
      var doc = app.documents.add();
      doc.documentPreferences.pageWidth = "{TRIM_W_MM}mm";
      doc.documentPreferences.pageHeight = "{TRIM_H_MM}mm";
      doc.documentPreferences.facingPages = true;
      doc.documentPreferences.pagesPerDocument = {len(pages)};
      doc.documentPreferences.documentBleedTopOffset = "{BLEED_MM}mm";
      doc.documentPreferences.documentBleedBottomOffset = "{BLEED_MM}mm";
      doc.documentPreferences.documentBleedInsideOrLeftOffset = "{BLEED_MM}mm";
      doc.documentPreferences.documentBleedOutsideOrRightOffset = "{BLEED_MM}mm";
      doc.marginPreferences.top = "16mm";
      doc.marginPreferences.bottom = "16mm";
      doc.marginPreferences.left = "16mm";
      doc.marginPreferences.right = "16mm";
      doc.marginPreferences.columnCount = 12;
      doc.marginPreferences.columnGutter = "5mm";
      return doc;
    }}

    // --- Swatch helpers (K-only: Black and Paper) ---
    function getBlack(doc) {{
      try {{ return doc.swatches.itemByName("[Black]"); }} catch (e) {{}}
      try {{ return doc.swatches.itemByName("Black"); }} catch (e) {{}}
      return doc.swatches.item(0);
    }}
    function getPaper(doc) {{
      try {{ return doc.swatches.itemByName("[Paper]"); }} catch (e) {{}}
      try {{ return doc.swatches.itemByName("Paper"); }} catch (e) {{}}
      return doc.swatches.item(1);
    }}

    // --- Frame helpers ---
    function pageBounds(page, bounds) {{
      var pb = page.bounds;
      var topOffset = Number(pb[0]);
      var leftOffset = Number(pb[1]);
      return [
        mm(topOffset + bounds[0]),
        mm(leftOffset + bounds[1]),
        mm(topOffset + bounds[2]),
        mm(leftOffset + bounds[3])
      ];
    }}

    function imageFrame(page, bounds, filePath, doc) {{
      var rect = page.rectangles.add();
      rect.geometricBounds = pageBounds(page, bounds);
      rect.strokeWeight = 0;
      try {{
        var f = File(filePath);
        if (f.exists) {{
          rect.place(f);
          rect.fit(FitOptions.FILL_PROPORTIONALLY);
          rect.fit(FitOptions.CENTER_CONTENT);
        }} else {{
          rect.fillColor = getBlack(doc);
          rect.transparencySettings.blendingSettings.opacity = 20;
        }}
      }} catch (e) {{
        try {{ rect.fillColor = getBlack(doc); }} catch (e2) {{}}
      }}
      return rect;
    }}

    function textFrame(page, bounds, text, size, fontStyle, swatch) {{
      var tf = page.textFrames.add();
      tf.geometricBounds = pageBounds(page, bounds);
      tf.contents = text;
      try {{
        tf.textFramePreferences.insetSpacing = ["2mm", "2mm", "2mm", "2mm"];
        tf.textFramePreferences.verticalJustification = VerticalJustification.TOP_ALIGN;
        tf.textFramePreferences.autoSizingReferencePoint = AutoSizingReferenceEnum.TOP_LEFT_POINT;
        tf.textFramePreferences.autoSizingType = AutoSizingTypeEnum.HEIGHT_ONLY;
        tf.texts[0].appliedFont = app.fonts.item("Helvetica");
        tf.texts[0].fontStyle = fontStyle || "Regular";
        tf.texts[0].pointSize = size;
        tf.texts[0].leading = size * 1.22;
        tf.texts[0].fillColor = swatch;
      }} catch (e) {{}}
      fitText(tf, 6.5);
      return tf;
    }}

    function fitText(tf, minSize) {{
      var attempts = 0;
      while (tf.overflows && attempts < 20) {{
        try {{
          var txt = tf.texts[0];
          txt.pointSize = Math.max(minSize, txt.pointSize - 0.3);
          txt.leading = txt.pointSize * 1.22;
        }} catch (e) {{ break; }}
        attempts++;
      }}
    }}

    function colorPanel(page, bounds, swatch, opacity) {{
      var rect = page.rectangles.add();
      rect.geometricBounds = pageBounds(page, bounds);
      rect.strokeWeight = 0;
      rect.fillColor = swatch;
      try {{ rect.transparencySettings.blendingSettings.opacity = opacity; }} catch (e) {{}}
      return rect;
    }}

    // --- Text zone calculator ---
    // Determines where text should go based on layout_metadata safe_zones and image positions.
    function computeTextBounds(pageData) {{
      var layout = pageData.layout || {{}};
      var anchors = layout.global_anchors || {{}};
      // Default text zone: primary column, full height
      var primaryX = anchors.primary || 54.4;
      var sidebarX = anchors.sidebar || 473.1;
      // Convert to trim-relative mm
      var bleedPt = {BLEED_PT};
      var ptToMm = {PT_TO_MM};
      var textLeft = (primaryX - bleedPt) * ptToMm;
      var textRight = (sidebarX - bleedPt) * ptToMm;
      var textTop = 16;  // top margin
      var textBottom = {TRIM_H_MM} - 16;  // bottom margin
      // If images occupy the text zone, push text to sidebar
      if (pageData.images && pageData.images.length > 0) {{
        var imgCoversLeft = false;
        for (var i = 0; i < pageData.images.length; i++) {{
          var img = pageData.images[i];
          if (img.bounds[1] <= textLeft + 20 && img.bounds[3] >= textRight - 20) {{
            imgCoversLeft = true;
          }}
        }}
        if (imgCoversLeft) {{
          textLeft = (sidebarX - bleedPt) * ptToMm;
          textRight = {TRIM_W_MM} - 12;
        }}
      }}
      return [textTop, textLeft, textBottom, textRight];
    }}

    // --- Audit helpers ---
    function countMissingLinks(doc) {{
      var missing = 0;
      for (var i = 0; i < doc.links.length; i++) {{
        try {{
          if (doc.links[i].status === LinkStatus.LINK_MISSING) missing++;
        }} catch (e) {{}}
      }}
      return missing;
    }}

    function countOversetFrames(doc) {{
      var overset = 0;
      for (var i = 0; i < doc.textFrames.length; i++) {{
        try {{
          if (doc.textFrames[i].isValid && doc.textFrames[i].overflows) overset++;
        }} catch (e) {{}}
      }}
      return overset;
    }}

    // --- Export and report ---
    function exportPdf(doc) {{
      var pdfFile = File(OUTPUT_PDF);
      if (!pdfFile.parent.exists) pdfFile.parent.create();
      var preset = null;
      try {{
        preset = app.pdfExportPresets.itemByName("[High Quality Print]");
        preset.name;
      }} catch (e) {{
        preset = app.pdfExportPresets.item(0);
      }}
      doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false, preset);
    }}

    function writeBuildReport(doc) {{
      var reportFile = File(OUTPUT_REPORT);
      if (!reportFile.parent.exists) reportFile.parent.create();
      var report = {{
        document: "The Visceral Theory of Sight (Handoff Build)",
        generatedAt: new Date().toString(),
        pageCount: doc.pages.length,
        facingPages: doc.documentPreferences.facingPages,
        trim: "US Letter landscape 279.4mm x 215.9mm",
        bleed: "3.175mm all sides",
        columns: 12,
        linkCount: doc.links.length,
        missingLinks: countMissingLinks(doc),
        textFrameCount: doc.textFrames.length,
        oversetTextFrames: countOversetFrames(doc),
        source: "handoff_package master_production_manifest.json",
        outputs: {{
          indd: OUTPUT_INDD,
          idml: OUTPUT_IDML,
          pdf: OUTPUT_PDF
        }}
      }};
      reportFile.encoding = "UTF-8";
      reportFile.open("w");
      reportFile.write(JSON.stringify(report, null, 2));
      reportFile.close();
    }}

    function saveFiles(doc) {{
      var inddFile = File(OUTPUT_INDD);
      var idmlFile = File(OUTPUT_IDML);
      if (!inddFile.parent.exists) inddFile.parent.create();
      if (inddFile.exists) inddFile.remove();
      if (idmlFile.exists) idmlFile.remove();
      doc.save(inddFile);
      doc.exportFile(ExportFormat.INDESIGN_MARKUP, idmlFile);
      exportPdf(doc);
      writeBuildReport(doc);
    }}

    // --- Main build ---
    function releaseOpenOutputDoc() {{
      var outputFile = File(OUTPUT_INDD);
      for (var d = app.documents.length - 1; d >= 0; d--) {{
        try {{
          var openDoc = app.documents[d];
          if (openDoc.fullName && openDoc.fullName.fsName === outputFile.fsName) {{
            openDoc.close(SaveOptions.NO);
          }}
        }} catch (e) {{}}
      }}
    }}

    releaseOpenOutputDoc();
    var doc = setupDoc();
    var ink = getBlack(doc);
    var paper = getPaper(doc);

    for (var p = 0; p < doc.pages.length && p < PAGE_DATA.length; p++) {{
      var page = doc.pages[p];
      var pd = PAGE_DATA[p];

      // Background: Paper fill
      colorPanel(page, [-{BLEED_MM}, -{BLEED_MM}, {TRIM_H_MM + BLEED_MM}, {TRIM_W_MM + BLEED_MM}], paper, 100);

      // Place images at exact manifest coordinates
      for (var img = 0; img < pd.images.length; img++) {{
        var imgData = pd.images[img];
        imageFrame(page, imgData.bounds, imgData.path, doc);
      }}

      // Place text content
      var content = pd.content || "";
      if (content.length > 0) {{
        var textBounds = computeTextBounds(pd);
        // Determine text size by page type
        var textSize = 8.5;
        var textStyle = "Regular";
        if (p === 0) {{
          // Cover: larger title text
          textSize = 22;
          textStyle = "Bold";
          textBounds = [60, 20, 200, 130];
        }} else if (p <= 3) {{
          textSize = 10;
        }} else if (content.length < 100) {{
          // Short text (pull quotes, page numbers)
          textSize = 14;
          textStyle = "Bold";
        }}
        textFrame(page, textBounds, content.replace(/\\n/g, "\\r"), textSize, textStyle, ink);
      }}

      // Page number
      var pageNumStr = ("0" + (p + 1)).slice(-2);
      textFrame(page, [{TRIM_H_MM - 12}, {TRIM_W_MM / 2 - 5}, {TRIM_H_MM - 4}, {TRIM_W_MM / 2 + 5}], pageNumStr, 6.5, "Regular", ink);
    }}

    // Final overset guard
    for (var i = 0; i < doc.textFrames.length; i++) {{
      try {{
        if (doc.textFrames[i].isValid && doc.textFrames[i].overflows) {{
          fitText(doc.textFrames[i], 6.5);
        }}
      }} catch (e) {{}}
    }}

    saveFiles(doc);

    }} catch (err) {{
      var errorFile = File({json.dumps((REPORTS_OUT / "handoff-build-error.txt").as_posix())});
      if (!errorFile.parent.exists) errorFile.parent.create();
      errorFile.encoding = "UTF-8";
      errorFile.open("w");
      errorFile.write("line: " + err.line + "\\nmessage: " + err.message + "\\nname: " + err.name);
      errorFile.close();
      throw err;
    }}
    """)
    return jsx


def generate_handoff_jsx(handoff_dir: Path) -> Path:
    """Main entry: load manifest, copy assets, generate JSX."""
    TEMPLATE_OUT.mkdir(parents=True, exist_ok=True)
    REPORTS_OUT.mkdir(parents=True, exist_ok=True)
    (ROUTE / "output" / "indesign").mkdir(parents=True, exist_ok=True)
    (ROUTE / "output" / "pdf").mkdir(parents=True, exist_ok=True)

    print("Loading handoff manifest...")
    manifest = load_manifest(handoff_dir)
    print(f"  {manifest['production_metadata']['total_pages']} pages, "
          f"{manifest['production_metadata']['total_assets']} assets")

    print("Copying handoff assets...")
    asset_dir = copy_handoff_assets(handoff_dir)

    print("Building page data...")
    pages = _build_page_data(manifest, asset_dir)

    print("Generating InDesign ExtendScript...")
    jsx = _generate_jsx(pages, asset_dir)

    output_jsx = TEMPLATE_OUT / "indesign-handoff-build.jsx"
    output_jsx.write_text(jsx, encoding="utf-8")
    print(f"  Wrote {output_jsx}")

    # Write generator report
    report = {
        "source": str(handoff_dir),
        "manifest_version": manifest["production_metadata"]["version"],
        "manifest_status": manifest["production_metadata"]["status"],
        "total_pages": manifest["production_metadata"]["total_pages"],
        "total_assets": manifest["production_metadata"]["total_assets"],
        "high_res_assets": manifest["production_metadata"]["high_res_assets"],
        "grid_system": manifest["production_metadata"]["grid_system"],
        "trim": {"width_mm": TRIM_W_MM, "height_mm": TRIM_H_MM, "name": "US Letter landscape"},
        "bleed_mm": BLEED_MM,
        "coordinate_mapping": {
            "source_system": "bleed-inclusive points (origin: top-left of bleed box)",
            "target_system": "InDesign page-relative mm (origin: top-left of trim)",
            "conversion": f"(pt - {BLEED_PT:.4f}) * {PT_TO_MM:.6f}",
        },
        "output_jsx": str(output_jsx),
        "asset_directory": str(asset_dir),
    }
    report_path = REPORTS_OUT / "handoff-build-generator-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Wrote {report_path}")

    return output_jsx


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_from_handoff.py /path/to/handoff_package")
        print("  The directory must contain master_production_manifest.json,")
        print("  production_layout_instructions.csv, and assets/")
        return 1

    handoff_dir = Path(sys.argv[1]).resolve()
    if not handoff_dir.is_dir():
        print(f"ERROR: not a directory: {handoff_dir}")
        return 1

    jsx_path = generate_handoff_jsx(handoff_dir)
    print(f"\nDone. To build in InDesign, run the generated script:")
    print(f"  {jsx_path}")
    print(f"\nOr use the COM bridge on Windows:")
    print(f"  python scripts/run_indesign_autobuild.py --handoff {handoff_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
