"""Video-frame capture: a separate capability from transcripts.

Having a transcript does not mean we may have the video. Frames come ONLY from a video file the user
uploaded (or otherwise has the right to use). We do not download YouTube video streams: that would
bypass YouTube's terms. When no file exists, cards say "Frame unavailable" and keep the timestamp link.
Never substitute a thumbnail or a generated image.

Deterministic code only (ffmpeg + Pillow); no AI involved.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from .config import MEDIA_DIR

YOUTUBE_FRAME_POLICY = ("Frame unavailable: UmmaCare does not download video from YouTube links (YouTube's terms "
                        "don't permit it). Upload your own copy of the video file to capture real frames.")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                              "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
        d = json.loads(out.stdout or "{}")
        if not any(s.get("codec_type") == "video" for s in d.get("streams", [])):
            return None
        return float(d["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError):
        return None


def _grab(path: Path, t: float, dest: Path) -> bool:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(dest)], capture_output=True, timeout=60)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def legibility(img_path: Path) -> float:
    """Higher for frames with crisp edges and contrast (slides, diagrams, on-screen text); low for blur/black."""
    with Image.open(img_path) as im:
        g = im.convert("L").resize((320, 180))
        edges = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
        contrast = ImageStat.Stat(g).stddev[0]
    return edges * 2 + contrast * 0.5


def capture_frame(video_path: Path, video_id: int, moment_id: int, start: float, end: float,
                  duration: float) -> tuple[str | None, float | None, str]:
    """Grab a few candidate frames inside the moment, keep the most legible one. Returns (relative path, time, note)."""
    if start is None or start < 0:
        return None, None, "Frame unavailable: this transcript has no timestamps, so we can't find the moment in the video."
    if start > duration:
        return None, None, f"Frame unavailable: the moment starts after the end of the uploaded file ({duration:.0f}s)."
    out_dir = MEDIA_DIR / f"video_{video_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    span = max(2.0, min(end, duration - 0.2) - start)
    candidates = sorted({round(min(duration - 0.2, start + span * f), 2) for f in (0.1, 0.35, 0.6, 0.85)})
    scored: list[tuple[float, float, Path]] = []
    for i, t in enumerate(candidates):
        p = out_dir / f"m{moment_id}_c{i}.jpg"
        if _grab(video_path, t, p):
            scored.append((legibility(p), t, p))
    if not scored:
        return None, None, "Frame unavailable: ffmpeg could not read a frame at this time."
    best = max(scored)
    final = out_dir / f"moment_{moment_id}.jpg"
    best[2].replace(final)
    for _, _, p in scored:
        p.unlink(missing_ok=True)
    note = (f"Captured from your uploaded video at {int(best[1]) // 60}:{int(best[1]) % 60:02d} "
            f"(sharpest of {len(scored)} nearby frames).")
    return str(final.relative_to(MEDIA_DIR)), best[1], note
