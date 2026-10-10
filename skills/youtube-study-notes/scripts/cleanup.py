#!/usr/bin/env python3
"""
cleanup.py - remove the heavy derived media from a study-notes run.

A run leaves behind frame JPEGs (and, if `--keep-video` was used, the video itself).
Both are derived from someone else's video, both are the large part of the footprint,
and neither is needed once `notes.md` exists — the notes carry the on-screen text
verbatim, so the *information* survives without the pixels.

Kept by default, because it is the evidence behind every claim:
    transcript.md, transcript.txt, meta.json, notes.md

Removed by default:
    <outdir>/frames/            (frame JPEGs + manifest.json)
    any video/audio file under <outdir> (mp4, mkv, webm, mov, m4a, part, ytdl)

Usage:
    python3 cleanup.py <outdir> [--keep-frames] [--dry-run]

Exit codes:
    0  success (including nothing to do)
    2  refused — the path does not look like a study-notes output directory
    3  refused — the path is too broad to delete from safely
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_NOT_OURS = 2
EXIT_TOO_BROAD = 3

# A directory is treated as one of our runs only if it carries one of these.
MARKERS = ("transcript.md", "transcript.txt", "meta.json", "notes.md", "frames")

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4a", ".mp3", ".part", ".ytdl"}

# Never operate on a directory shallower than this many path segments, so a typo
# cannot turn into a recursive delete of $HOME or /.
MIN_DEPTH = 2


def die(msg: str, code: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def human(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove derived media from a study-notes run.")
    ap.add_argument("outdir", help="the run's output directory")
    ap.add_argument("--keep-frames", action="store_true", help="keep frames/ (the on-screen evidence)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be removed, remove nothing")
    args = ap.parse_args()

    outdir = Path(args.outdir).expanduser().resolve()

    if not outdir.is_dir():
        die(f"not a directory: {outdir}", EXIT_NOT_OURS)

    if len(outdir.parts) < MIN_DEPTH + 1:
        die(f"refusing to clean a path this broad: {outdir}", EXIT_TOO_BROAD)

    if not any((outdir / m).exists() for m in MARKERS):
        die(
            f"{outdir} does not look like a study-notes output directory "
            f"(none of {', '.join(MARKERS)} present)",
            EXIT_NOT_OURS,
        )

    targets: list[Path] = []

    frames_dir = outdir / "frames"
    if frames_dir.is_dir() and not args.keep_frames:
        targets.append(frames_dir)

    for path in outdir.rglob("*"):
        if any(part == "frames" for part in path.parts[len(outdir.parts) :]):
            continue  # already counted, or deliberately kept
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES:
            targets.append(path)

    targets = sorted(set(targets))

    if not targets:
        print(json.dumps({"status": "ok", "removed": 0, "freed_bytes": 0, "outdir": str(outdir)}))
        return EXIT_OK

    freed = human(targets)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "outdir": str(outdir),
                    "would_remove": [str(t.relative_to(outdir)) for t in targets],
                    "freed_bytes": freed,
                },
                ensure_ascii=False,
            )
        )
        return EXIT_OK

    removed: list[str] = []
    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        else:
            t.unlink(missing_ok=True)
        removed.append(str(t.relative_to(outdir)))

    print(
        json.dumps(
            {
                "status": "ok",
                "outdir": str(outdir),
                "removed": removed,
                "freed_bytes": freed,
                "kept": sorted(m for m in MARKERS if (outdir / m).exists()),
            },
            ensure_ascii=False,
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
