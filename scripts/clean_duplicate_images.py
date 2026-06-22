"""Find and clean up duplicate image files.

Scans a directory (recursively) for duplicate images by content hash.
Groups duplicates together and lets you choose which to keep or auto-remove.

Usage:
    python scripts/clean_duplicate_images.py C:\path\to\images
    python scripts/clean_duplicate_images.py C:\path\to\images --auto-keep newest
    python scripts/clean_duplicate_images.py C:\path\to\images --auto-keep oldest
    python scripts/clean_duplicate_images.py C:\path\to\images --auto-keep shortest-name
    python scripts/clean_duplicate_images.py C:\path\to\images --dry-run
    python scripts/clean_duplicate_images.py C:\path\to\images --min-size 100  # skip files < 100KB

Options:
    --auto-keep newest         Automatically keep the most recently modified file
    --auto-keep oldest         Automatically keep the oldest file
    --auto-keep shortest-name  Automatically keep the file with the shortest name
    --dry-run                  Show what would be deleted without deleting
    --min-size KB              Only scan files larger than this (in KB)
    --extensions               Comma-separated list of extensions (default: png,jpg,jpeg,tiff,tif,psd,ai,bmp,gif,webp)
    --output REPORT            Write a CSV report of duplicates found
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path


IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tiff", ".tif",
    ".psd", ".ai", ".bmp", ".gif", ".webp",
    ".svg", ".eps", ".indd", ".pdf",
}


def hash_file(path: Path, chunk_size: int = 65536) -> str:
    """SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(
    root: Path,
    extensions: set[str],
    min_size_bytes: int = 0,
) -> dict[str, list[Path]]:
    """Scan directory and group files by content hash."""
    hash_map: dict[str, list[Path]] = defaultdict(list)
    file_count = 0

    print(f"Scanning: {root}")
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in extensions:
                continue
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size < min_size_bytes:
                continue

            file_count += 1
            if file_count % 100 == 0:
                print(f"  ...scanned {file_count} files", end="\r")

            file_hash = hash_file(fpath)
            hash_map[file_hash].append(fpath)

    print(f"  Scanned {file_count} image files total.")

    # Filter to only groups with duplicates
    return {h: paths for h, paths in hash_map.items() if len(paths) > 1}


def pick_keeper(files: list[Path], strategy: str) -> Path:
    """Pick which file to keep based on strategy."""
    if strategy == "newest":
        return max(files, key=lambda f: f.stat().st_mtime)
    elif strategy == "oldest":
        return min(files, key=lambda f: f.stat().st_mtime)
    elif strategy == "shortest-name":
        return min(files, key=lambda f: len(f.name))
    else:
        return files[0]


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024*1024):.1f} MB"


def main():
    parser = argparse.ArgumentParser(description="Find and remove duplicate image files")
    parser.add_argument("directory", help="Directory to scan for duplicates")
    parser.add_argument(
        "--auto-keep",
        choices=["newest", "oldest", "shortest-name"],
        help="Auto-select which file to keep (skip interactive prompts)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show duplicates without deleting")
    parser.add_argument("--min-size", type=int, default=0, help="Minimum file size in KB to scan")
    parser.add_argument(
        "--extensions",
        default=None,
        help="Comma-separated extensions to scan (default: common image formats)",
    )
    parser.add_argument("--output", help="Write CSV report to this path")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    if not root.exists():
        print(f"ERROR: Directory not found: {root}")
        sys.exit(1)

    # Parse extensions
    if args.extensions:
        extensions = {f".{e.strip().lstrip('.')}" for e in args.extensions.split(",")}
    else:
        extensions = IMAGE_EXTENSIONS

    min_bytes = args.min_size * 1024

    # Find duplicates
    duplicates = find_duplicates(root, extensions, min_bytes)

    if not duplicates:
        print("\nNo duplicates found!")
        return

    # Stats
    total_groups = len(duplicates)
    total_dupes = sum(len(files) - 1 for files in duplicates.values())
    total_waste = sum(
        sum(f.stat().st_size for f in files[1:])
        for files in duplicates.values()
    )

    print(f"\nFound {total_groups} groups of duplicates ({total_dupes} extra files)")
    print(f"Potential space savings: {format_size(total_waste)}")
    print(f"{'='*60}\n")

    # CSV report
    csv_rows = []
    deleted_count = 0
    saved_bytes = 0

    for i, (file_hash, files) in enumerate(duplicates.items(), 1):
        files_sorted = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
        size = files_sorted[0].stat().st_size

        print(f"Group {i}/{total_groups} — {format_size(size)} each, {len(files_sorted)} copies:")
        for j, f in enumerate(files_sorted):
            mtime = os.path.getmtime(f)
            from datetime import datetime
            mod_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            marker = ""
            print(f"  [{j+1}] {f.name}  ({mod_date})  {f.parent}")

        if args.auto_keep:
            keeper = pick_keeper(files_sorted, args.auto_keep)
            print(f"  -> Keeping: {keeper.name} (strategy: {args.auto_keep})")

            for f in files_sorted:
                csv_rows.append({
                    "hash": file_hash[:12],
                    "file": str(f),
                    "size": size,
                    "action": "KEEP" if f == keeper else "DELETE",
                })
                if f != keeper:
                    if not args.dry_run:
                        try:
                            f.unlink()
                            deleted_count += 1
                            saved_bytes += size
                        except OSError as e:
                            print(f"  ERROR deleting {f}: {e}")
                    else:
                        deleted_count += 1
                        saved_bytes += size
        elif not args.dry_run:
            # Interactive mode
            try:
                choice = input(f"  Keep which? [1-{len(files_sorted)}, s=skip, q=quit]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                break

            if choice.lower() == "q":
                break
            elif choice.lower() == "s":
                print("  Skipped.")
                continue
            elif choice.isdigit() and 1 <= int(choice) <= len(files_sorted):
                keeper_idx = int(choice) - 1
                keeper = files_sorted[keeper_idx]
                for j, f in enumerate(files_sorted):
                    if j != keeper_idx:
                        try:
                            f.unlink()
                            deleted_count += 1
                            saved_bytes += size
                            print(f"  Deleted: {f.name}")
                        except OSError as e:
                            print(f"  ERROR: {e}")
            else:
                print("  Skipped (invalid input).")
        else:
            # Dry run without auto-keep — just report
            for f in files_sorted:
                csv_rows.append({
                    "hash": file_hash[:12],
                    "file": str(f),
                    "size": size,
                    "action": "DUPLICATE",
                })

        print()

    # Summary
    action = "Would delete" if args.dry_run else "Deleted"
    print(f"{'='*60}")
    print(f"{action} {deleted_count} duplicate files")
    print(f"Space {'savings' if args.dry_run else 'saved'}: {format_size(saved_bytes)}")

    # Write CSV report
    if args.output and csv_rows:
        output_path = Path(args.output)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["hash", "file", "size", "action"])
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"Report written to: {output_path}")


if __name__ == "__main__":
    main()
