#!/usr/bin/env python3
"""
yt_transcript.py - fetch a YouTube video's OWN captions and emit a clean transcript bundle.

No ASR, no third-party transcript sites: this uses yt-dlp to pull the caption track
YouTube already publishes (human-written preferred, auto-generated as fallback).

Usage:
    python3 yt_transcript.py <url-or-video-id> [--out DIR] [--lang en,hi]
                             [--paragraph-seconds 45] [--print]

Writes into --out (default: ./<video-id>-transcript/):
    transcript.md    timestamped, chaptered, readable transcript   <- feed this to the model
    transcript.txt   flat plain text, no timestamps
    meta.json        title, channel, duration, chapters, caption provenance

Exit codes:
    0  success
    2  yt-dlp not installed
    3  no captions available for this video (the expected "no captions" branch)
    4  download or parse failure
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

EXIT_OK = 0
EXIT_NO_YTDLP = 2
EXIT_NO_CAPTIONS = 3
EXIT_FAILED = 4

INLINE_TAG = re.compile(r"<[^>]+>")
TIMESTAMP_LINE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def die(msg: str, code: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def to_seconds(stamp: str) -> float:
    stamp = stamp.replace(",", ".")
    parts = stamp.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def hhmmss(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def normalize_target(raw: str) -> tuple[str, str | None]:
    """Return (url, expected_video_id)."""
    raw = raw.strip()
    match = VIDEO_ID.search(raw)
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw, match.group(1) if match else None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={raw}", raw
    if match:
        return raw, match.group(1)
    die(f"could not parse a YouTube video from {raw!r}", EXIT_FAILED)
    return "", None  # unreachable


def fetch_metadata(url: str) -> dict:
    proc = run(
        ["yt-dlp", "--dump-json", "--no-warnings", "--no-playlist", "--skip-download", url],
        timeout=180,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = (proc.stderr or "").strip().splitlines()
        die("yt-dlp could not read this video:\n  " + "\n  ".join(detail[-4:]), EXIT_FAILED)
    return json.loads(proc.stdout.splitlines()[0])


def pick_track(meta: dict, langs: list[str]) -> tuple[str, str] | None:
    """Choose (kind, lang) where kind is 'manual' or 'auto'. Manual always wins."""
    for kind, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
        table = meta.get(key) or {}
        if not table:
            continue
        for want in langs:
            for have in table:
                if have.lower() == want.lower() or have.lower().startswith(want.lower() + "-"):
                    return kind, have
        original = meta.get("language")
        if original and original in table:
            return kind, original
        for fallback in ("en", "en-US", "en-orig"):
            if fallback in table:
                return kind, fallback
        return kind, sorted(table)[0]
    return None


def download_subs(url: str, workdir: Path, kind: str, lang: str) -> Path:
    flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
    proc = run(
        [
            "yt-dlp", "--skip-download", "--no-warnings", "--no-playlist",
            flag, "--sub-langs", lang, "--sub-format", "vtt/srt/best",
            "--convert-subs", "vtt",
            "-o", str(workdir / "%(id)s.%(ext)s"), url,
        ],
        timeout=300,
    )
    found = sorted(workdir.glob("*.vtt")) + sorted(workdir.glob("*.srt"))
    if found:
        return found[0]
    tail = (proc.stderr or "").strip().splitlines()
    die(
        "caption track was listed but could not be downloaded:\n  "
        + (tail[-1] if tail else "unknown error"),
        EXIT_FAILED,
    )
    raise SystemExit(EXIT_FAILED)  # unreachable


def parse_cues(path: Path) -> list[tuple[float, str]]:
    """Parse VTT/SRT into (start_seconds, text) cues, dropping inline markup."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    cues: list[tuple[float, str]] = []
    pending_start: float | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal pending_start, buffer
        if pending_start is not None and buffer:
            text = " ".join(buffer)
            text = re.sub(r"\s+", " ", INLINE_TAG.sub("", html.unescape(text))).strip()
            if text:
                cues.append((pending_start, text))
        pending_start, buffer = None, []

    for line in raw.splitlines():
        stripped = line.strip()
        match = TIMESTAMP_LINE.search(stripped)
        if match:
            flush()
            pending_start = to_seconds(match.group("start"))
            continue
        if not stripped:
            flush()
            continue
        if stripped.upper().startswith("WEBVTT") or stripped.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if re.fullmatch(r"\d+", stripped):  # SRT sequence number
            continue
        if pending_start is None:
            continue
        buffer.append(stripped)
    flush()
    return cues


def dedupe_rolling(cues: list[tuple[float, str]], window: int = 12) -> list[tuple[float, str]]:
    """Collapse YouTube's rolling auto-caption repetition.

    Auto-captions re-emit the previous line alongside each new one, and split a
    single sentence across cues. Emitting only lines not seen in the recent window
    leaves one clean copy of each phrase.
    """
    out: list[tuple[float, str]] = []
    recent: deque[str] = deque(maxlen=window)
    for start, text in cues:
        pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n", text) if p.strip()]
        for piece in pieces:
            key = piece.lower().strip(" .,!?-")
            if not key or key in recent:
                continue
            recent.append(key)
            if out and out[-1][0] == start:
                out[-1] = (start, f"{out[-1][1]} {piece}".strip())
            else:
                out.append((start, piece))
    return out


def build_sections(
    cues: list[tuple[float, str]], chapters: list[dict], paragraph_seconds: int
) -> list[dict]:
    """Group cues into chapter-scoped, time-boxed paragraphs."""
    marks = [
        (float(c.get("start_time") or 0), (c.get("title") or "").strip())
        for c in chapters
        if (c.get("title") or "").strip()
    ]
    marks.sort()
    sections: list[dict] = []
    current: dict | None = None
    para_start = 0.0

    def chapter_for(t: float) -> str:
        label = ""
        for start, title in marks:
            if t >= start:
                label = title
            else:
                break
        return label

    for start, text in cues:
        label = chapter_for(start)
        if current is None or (label and label != current["chapter"]) or (
            start - para_start >= paragraph_seconds
        ):
            current = {"chapter": label, "start": start, "paras": []}
            sections.append(current)
            para_start = start
        current["paras"].append((start, text))
    return sections


def render(sections: list[dict]) -> tuple[str, str]:
    md: list[str] = []
    flat: list[str] = []
    last_chapter = None
    for section in sections:
        if section["chapter"] and section["chapter"] != last_chapter:
            md.append(f"\n## {section['chapter']}\n")
            last_chapter = section["chapter"]
        for start, text in section["paras"]:
            md.append(f"**[{hhmmss(start)}]** {text}")
            flat.append(text)
    return "\n".join(md).strip(), " ".join(flat).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a YouTube video's own captions.")
    ap.add_argument("target", help="YouTube URL or 11-character video id")
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--lang", default="en", help="comma-separated language preference, e.g. en,hi")
    ap.add_argument("--paragraph-seconds", type=int, default=45)
    ap.add_argument("--print", dest="echo", action="store_true", help="also print transcript.md")
    args = ap.parse_args()

    if shutil.which("yt-dlp") is None:
        die("yt-dlp is not installed. Install it with: brew install yt-dlp", EXIT_NO_YTDLP)

    url, expected_id = normalize_target(args.target)
    langs = [x.strip() for x in args.lang.split(",") if x.strip()]
    meta = fetch_metadata(url)

    video_id = meta.get("id") or expected_id or "video"
    track = pick_track(meta, langs)
    if track is None:
        print(
            json.dumps(
                {
                    "status": "no_captions",
                    "video_id": video_id,
                    "title": meta.get("title"),
                    "duration_seconds": meta.get("duration"),
                },
                ensure_ascii=False,
            )
        )
        die(
            f"'{meta.get('title')}' publishes no caption track at all "
            "(not even auto-generated). The captions-only path cannot transcribe it.",
            EXIT_NO_CAPTIONS,
        )
        return EXIT_NO_CAPTIONS

    kind, lang = track
    outdir = Path(args.out) if args.out else Path.cwd() / f"{video_id}-transcript"
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        sub_path = download_subs(url, Path(tmp), kind, lang)
        cues = dedupe_rolling(parse_cues(sub_path))

    if not cues:
        die("caption track downloaded but contained no readable text", EXIT_FAILED)

    chapters = meta.get("chapters") or []
    sections = build_sections(cues, chapters, args.paragraph_seconds)
    markdown, flat = render(sections)

    header = [
        f"# {meta.get('title') or video_id}",
        "",
        f"- Channel: {meta.get('uploader') or meta.get('channel') or 'unknown'}",
        f"- Duration: {hhmmss(meta.get('duration') or 0)}",
        f"- URL: {meta.get('webpage_url') or url}",
        f"- Captions: {kind} ({lang})",
        f"- Segments: {len(cues)}",
    ]
    if meta.get("upload_date"):
        d = str(meta["upload_date"])
        header.append(f"- Published: {d[:4]}-{d[4:6]}-{d[6:8]}")
    body = "\n".join(header) + "\n\n" + markdown + "\n"

    (outdir / "transcript.md").write_text(body, encoding="utf-8")
    (outdir / "transcript.txt").write_text(flat, encoding="utf-8")
    (outdir / "meta.json").write_text(
        json.dumps(
            {
                "id": video_id,
                "title": meta.get("title"),
                "uploader": meta.get("uploader"),
                "duration_seconds": meta.get("duration"),
                "upload_date": meta.get("upload_date"),
                "webpage_url": meta.get("webpage_url") or url,
                "caption_kind": kind,
                "caption_lang": lang,
                "segments": len(cues),
                "chapters": chapters,
                "transcript_words": len(flat.split()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if args.echo:
        print(body)

    print(
        json.dumps(
            {
                "status": "ok",
                "outdir": str(outdir),
                "title": meta.get("title"),
                "caption_kind": kind,
                "caption_lang": lang,
                "segments": len(cues),
                "words": len(flat.split()),
                "chapters": len(chapters),
            },
            ensure_ascii=False,
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        die("yt-dlp timed out", EXIT_FAILED)
    except KeyboardInterrupt:
        sys.exit(130)
