#!/usr/bin/env python3
"""
video_frames.py - download a video and extract scene-change frames for visual analysis.

Downloads with yt-dlp, detects shot boundaries with ffmpeg's scene score, and writes one
representative JPEG per scene plus a manifest mapping every frame to its timestamp. The
companion step feeds those frames to a vision model; this script only produces them.

Usage:
    python3 video_frames.py <url-or-path> [--out DIR] [--max-frames 48]
                            [--threshold 0.35] [--width 1024] [--max-height 720]
                            [--keep-video] [--start 0] [--end 0]

Writes into --out (default: ./<video-id>-frames/):
    frames/frame_0001.jpg ...
    manifest.json    [{frame, t, hh:mm:ss}, ...] ordered by time
    video.mp4        only with --keep-video

Exit codes:
    0  success
    2  yt-dlp or ffmpeg missing
    3  download failed
    4  frame extraction failed
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_OK = 0
EXIT_NO_TOOL = 2
EXIT_DOWNLOAD = 3
EXIT_EXTRACT = 4

PTS = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def die(msg: str, code: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def hhmmss(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ffmpeg_supports_fps_mode() -> bool:
    """ffmpeg >= 5 replaced -vsync with -fps_mode."""
    try:
        proc = run(["ffmpeg", "-hide_banner", "-h", "full"], timeout=30)
    except Exception:
        return False
    return "-fps_mode" in (proc.stdout or "") + (proc.stderr or "")


def download(url: str, workdir: Path, max_height: int, start: int, end: int) -> Path:
    fmt = (
        f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={max_height}]/bv*[height<={max_height}]/b"
    )
    cmd = [
        "yt-dlp", "--no-warnings", "--no-playlist",
        "-f", fmt, "--merge-output-format", "mp4",
        "-o", str(workdir / "video.%(ext)s"), url,
    ]
    if start or end:
        section = f"*{start}-{end if end else 'inf'}"
        cmd += ["--download-sections", section, "--force-keyframes-at-cuts"]
    proc = run(cmd, timeout=5400)
    found = [
        p for p in sorted(workdir.glob("video.*"))
        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if found:
        return found[0]
    tail = (proc.stderr or "").strip().splitlines()
    die("video download failed:\n  " + (tail[-1] if tail else "unknown error"), EXIT_DOWNLOAD)
    raise SystemExit(EXIT_DOWNLOAD)  # unreachable


def probe_duration(video: Path) -> float:
    proc = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        timeout=60,
    )
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def detect_scenes(video: Path, outdir: Path, threshold: float, width: int) -> list[float]:
    """Extract one frame per detected scene; return their timestamps in order."""
    fps_flag = ["-fps_mode", "vfr"] if ffmpeg_supports_fps_mode() else ["-vsync", "vfr"]
    pattern = str(outdir / "frame_%04d.jpg")
    vf = f"select='gt(scene,{threshold})',showinfo,scale={width}:-2"
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
        "-vf", vf, *fps_flag, "-q:v", "3", "-an", pattern,
    ]
    proc = run(cmd, timeout=3600)
    stamps = [float(m) for m in PTS.findall(proc.stderr or "")]
    frames = sorted(outdir.glob("frame_*.jpg"))
    if not frames:
        return []
    # showinfo emits one line per selected frame, in output order. If the counts
    # disagree the mapping is untrustworthy, so let the caller fall back.
    if len(stamps) != len(frames):
        return []
    return stamps


def uniform_sample(video: Path, outdir: Path, count: int, width: int, duration: float) -> list[float]:
    """Fallback: evenly spaced frames when scene detection finds nothing usable."""
    if duration <= 0 or count <= 0:
        return []
    step = duration / (count + 1)
    stamps: list[float] = []
    for i in range(count):
        t = step * (i + 1)
        target = outdir / f"frame_{i + 1:04d}.jpg"
        run(
            ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(target)],
            timeout=120,
        )
        if target.exists():
            stamps.append(t)
    return stamps


def thin(stamps: list[float], frames: list[Path], outdir: Path, maximum: int) -> tuple[list[float], list[Path]]:
    """Evenly subsample down to `maximum`, renumbering kept frames to stay contiguous."""
    if len(frames) <= maximum:
        return stamps, frames
    idx = [round(i * (len(frames) - 1) / (maximum - 1)) for i in range(maximum)]
    idx = sorted(set(idx))
    kept_stamps = [stamps[i] for i in idx]
    tmp = outdir / "_keep"
    tmp.mkdir(exist_ok=True)
    kept: list[Path] = []
    for n, i in enumerate(idx, start=1):
        dest = tmp / f"frame_{n:04d}.jpg"
        shutil.copy2(frames[i], dest)
        kept.append(dest)
    for f in frames:
        f.unlink(missing_ok=True)
    for f in kept:
        f.rename(outdir / f.name)
    shutil.rmtree(tmp, ignore_errors=True)
    return kept_stamps, sorted(outdir.glob("frame_*.jpg"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract scene-change frames from a video.")
    ap.add_argument("target", help="YouTube URL or local video path")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-frames", type=int, default=48)
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--max-height", type=int, default=720)
    ap.add_argument("--keep-video", action="store_true")
    ap.add_argument("--start", type=int, default=0, help="start second (URL only)")
    ap.add_argument("--end", type=int, default=0, help="end second, 0 = to the end (URL only)")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            die(f"{tool} not found on PATH. Install it with: brew install ffmpeg", EXIT_NO_TOOL)

    is_url = args.target.startswith(("http://", "https://"))
    if is_url and shutil.which("yt-dlp") is None:
        die("yt-dlp not found on PATH. Install it with: brew install yt-dlp", EXIT_NO_TOOL)
    if not is_url and not Path(args.target).exists():
        die(f"local video not found: {args.target}", EXIT_DOWNLOAD)

    keep = args.keep_video
    with tempfile.TemporaryDirectory() as tmp:
        if is_url:
            video = download(args.target, Path(tmp), args.max_height, args.start, args.end)
        else:
            video = Path(args.target)

        stem = video.stem if not is_url else "video"
        outdir = Path(args.out) if args.out else Path.cwd() / f"{stem}-frames"
        frames_dir = outdir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        duration = probe_duration(video)
        stamps = detect_scenes(video, frames_dir, args.threshold, args.width)
        method = "scene"

        if not stamps:
            frames_dir.mkdir(parents=True, exist_ok=True)
            for stale in frames_dir.glob("frame_*.jpg"):
                stale.unlink()
            stamps = uniform_sample(video, frames_dir, args.max_frames, args.width, duration)
            method = "uniform"

        if not stamps:
            die("no frames could be extracted from this video", EXIT_EXTRACT)

        frames = sorted(frames_dir.glob("frame_*.jpg"))
        stamps, frames = thin(stamps, frames, frames_dir, args.max_frames)

        manifest = [
            {"frame": f.name, "t": round(t, 3), "time": hhmmss(t)}
            for f, t in zip(frames, stamps)
        ]
        (outdir / "manifest.json").write_text(
            json.dumps(
                {
                    "source": args.target,
                    "duration_seconds": round(duration, 2),
                    "duration": hhmmss(duration),
                    "method": method,
                    "threshold": args.threshold if method == "scene" else None,
                    "frame_count": len(manifest),
                    "frames": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if keep and is_url:
            shutil.copy2(video, outdir / video.name)

    print(
        json.dumps(
            {
                "status": "ok",
                "outdir": str(outdir),
                "method": method,
                "frames": len(manifest),
                "duration": hhmmss(duration),
            },
            ensure_ascii=False,
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        die("ffmpeg or yt-dlp timed out", EXIT_EXTRACT)
    except KeyboardInterrupt:
        sys.exit(130)
