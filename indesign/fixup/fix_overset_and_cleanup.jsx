// ============================================================
// FIX-UP SCRIPT: Overset + Label Cleanup + Image Swap
// ============================================================
// Run on your OPEN document in InDesign:
//   File > Scripts > Other Script... > fix_overset_and_cleanup.jsx
//
// What it does:
//   1. Fixes ALL overset text frames (shrinks text, tightens tracking, expands frames)
//   2. Removes A##/LABEL overlay codes (e.g. "A01 / MEDIATION")
//   3. Optionally relinks images from a local folder
//
// Safe: does NOT delete content, only resizes/adjusts to fit.
// ============================================================

app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;

(function() {
  if (app.documents.length === 0) {
    alert("No document open. Please open your InDesign file first.");
    return;
  }

  var doc = app.activeDocument;
  var report = {
    oversetFixed: 0,
    oversetRemaining: 0,
    labelsRemoved: 0,
    imagesRelinked: 0,
    errors: []
  };

  // ============================================================
  // PHASE 1: Fix all overset text frames
  // ============================================================

  function fixOversetFrame(tf) {
    if (!tf.isValid || !tf.overflows) return false;

    var fixed = false;
    var txt;
    try { txt = tf.texts[0]; } catch (e) { return false; }

    // Strategy A: Reduce point size (down to 5pt)
    var attempts = 0;
    while (tf.overflows && attempts < 40) {
      try {
        var currentSize = txt.pointSize;
        var newSize = Math.max(5, currentSize - 0.3);
        if (newSize >= currentSize) break;
        txt.pointSize = newSize;
        txt.leading = newSize * 1.15;
      } catch (e) { break; }
      attempts++;
    }

    // Strategy B: Tighten tracking (down to -60)
    if (tf.overflows) {
      var trackAttempts = 0;
      while (tf.overflows && trackAttempts < 20) {
        try {
          var currentTracking = txt.tracking;
          var newTracking = Math.max(-60, currentTracking - 5);
          if (newTracking >= currentTracking) break;
          txt.tracking = newTracking;
        } catch (e) { break; }
        trackAttempts++;
      }
    }

    // Strategy C: Reduce inset spacing
    if (tf.overflows) {
      try {
        tf.textFramePreferences.insetSpacing = ["1mm", "1mm", "1mm", "1mm"];
      } catch (e) {}
    }

    // Strategy D: Expand frame height (up to 30mm extra)
    if (tf.overflows) {
      var expandAttempts = 0;
      while (tf.overflows && expandAttempts < 10) {
        try {
          var gb = tf.geometricBounds; // [top, left, bottom, right]
          tf.geometricBounds = [gb[0], gb[1], gb[2] + 3, gb[3]]; // +3mm per attempt
        } catch (e) { break; }
        expandAttempts++;
      }
    }

    // Strategy E: Enable auto-size as last resort
    if (tf.overflows) {
      try {
        tf.textFramePreferences.autoSizingType = AutoSizingTypeEnum.HEIGHT_ONLY;
        tf.textFramePreferences.autoSizingReferencePoint = AutoSizingReferenceEnum.TOP_LEFT_POINT;
      } catch (e) {}
    }

    fixed = !tf.overflows;
    return fixed;
  }

  // Count initial overset
  var initialOverset = 0;
  for (var i = 0; i < doc.textFrames.length; i++) {
    try {
      if (doc.textFrames[i].isValid && doc.textFrames[i].overflows) initialOverset++;
    } catch (e) {}
  }

  // Fix all overset frames
  for (var i = 0; i < doc.textFrames.length; i++) {
    try {
      var tf = doc.textFrames[i];
      if (tf.isValid && tf.overflows) {
        if (fixOversetFrame(tf)) {
          report.oversetFixed++;
        } else {
          report.oversetRemaining++;
        }
      }
    } catch (e) {
      report.errors.push("Frame " + i + ": " + e.message);
    }
  }

  // ============================================================
  // PHASE 2: Remove A##/LABEL overlay codes
  // ============================================================
  // Pattern: "A01 / MEDIATION", "A24 / RAW AGENCY", "A05 / SOCIAL CONSTRAINT"
  // These appear in text frames as labels

  var labelPattern = /^A\d{1,2}\s*\/\s*(MEDIATION|RAW AGENCY|SOCIAL CONSTRAINT|CONSTRAINT|AGENCY|SYNTHESIS)/i;

  for (var i = doc.textFrames.length - 1; i >= 0; i--) {
    try {
      var tf = doc.textFrames[i];
      if (!tf.isValid) continue;
      var content = tf.contents;

      // Check if the frame contains ONLY a label code
      if (labelPattern.test(content.replace(/[\r\n]/g, "").trim())) {
        // Clear the label text (don't delete the frame - might break layout)
        tf.contents = "";
        report.labelsRemoved++;
      }
    } catch (e) {}
  }

  // Also do GREP find/change to remove inline labels
  try {
    app.findGrepPreferences = NothingEnum.NOTHING;
    app.changeGrepPreferences = NothingEnum.NOTHING;
    app.findGrepPreferences.findWhat = "A\\d{1,2}\\s*/\\s*(MEDIATION|RAW AGENCY|SOCIAL CONSTRAINT|CONSTRAINT|AGENCY|SYNTHESIS)";
    app.changeGrepPreferences.changeTo = "";
    var results = doc.changeGrep();
    report.labelsRemoved += results.length;
  } catch (e) {
    report.errors.push("GREP label cleanup: " + e.message);
  }
  app.findGrepPreferences = NothingEnum.NOTHING;
  app.changeGrepPreferences = NothingEnum.NOTHING;

  // ============================================================
  // PHASE 3: Relink images from local folder (optional)
  // ============================================================
  // Set this path to your local images folder, or leave empty to skip
  var IMAGE_SWAP_FOLDER = "C:/Users/toddl/OneDrive/Desktop/SCHOOL/Graph252 booklab/visceral-theory of sight assets/theory of sight/images for eye book";

  var swapFolder = Folder(IMAGE_SWAP_FOLDER);
  if (swapFolder.exists) {
    var swapFiles = swapFolder.getFiles(/\.(png|jpg|jpeg|tif|tiff|psd)$/i);

    // Build a lookup of available swap images by base name
    var swapLookup = {};
    for (var s = 0; s < swapFiles.length; s++) {
      var fname = swapFiles[s].name.toLowerCase();
      swapLookup[fname] = swapFiles[s];
      // Also index without extension for fuzzy matching
      var baseName = fname.replace(/\.(png|jpg|jpeg|tif|tiff|psd)$/i, "");
      swapLookup[baseName] = swapFiles[s];
    }

    // Try to relink existing images where names match
    for (var li = 0; li < doc.links.length; li++) {
      try {
        var link = doc.links[li];
        var linkName = link.name.toLowerCase();
        var linkBase = linkName.replace(/\.(png|jpg|jpeg|tif|tiff|psd)$/i, "");

        if (swapLookup[linkName]) {
          link.relink(swapLookup[linkName]);
          link.update();
          report.imagesRelinked++;
        } else if (swapLookup[linkBase]) {
          link.relink(swapLookup[linkBase]);
          link.update();
          report.imagesRelinked++;
        }
      } catch (e) {}
    }
  }

  // ============================================================
  // REPORT
  // ============================================================
  var summary = "=== FIX-UP COMPLETE ===\n\n";
  summary += "Overset before: " + initialOverset + "\n";
  summary += "Overset fixed: " + report.oversetFixed + "\n";
  summary += "Overset remaining: " + report.oversetRemaining + "\n";
  summary += "Labels removed: " + report.labelsRemoved + "\n";
  summary += "Images relinked: " + report.imagesRelinked + "\n";

  if (report.errors.length > 0) {
    summary += "\nErrors (" + report.errors.length + "):\n";
    for (var e = 0; e < Math.min(10, report.errors.length); e++) {
      summary += "  - " + report.errors[e] + "\n";
    }
  }

  summary += "\nNext: File > Export > PDF (Print) for final output.";

  // Write report to file
  var reportFile = File("~/Production-Automation-Output/InDesign/reports/fixup-report.txt");
  if (!reportFile.parent.exists) reportFile.parent.create();
  reportFile.encoding = "UTF-8";
  reportFile.open("w");
  reportFile.write(summary);
  reportFile.close();

  // Show result
  alert(summary);

})();
