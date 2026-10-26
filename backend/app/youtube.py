"""YouTube links and transcripts.

Two different things live here, and the app never blurs them:
  * retrieving captions that already exist on YouTube (youtube-transcript-api), and
  * accepting a transcript the user pastes or uploads (e.g. an .srt/.vtt file, or text copied from YouTube's
    "Show transcript" panel).
We do NOT generate transcripts from audio: no speech-recognition service is configured (see README).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    url = url.strip()
    if _ID.match(url):
        return url
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        cand = u.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            cand = parse_qs(u.query).get("v", [""])[0]
        else:
            m = re.match(r"^/(?:embed|shorts|live|v)/([^/?#]+)", u.path)
            cand = m.group(1) if m else ""
    else:
        return None
    return cand if _ID.match(cand) else None


def watch_url(video_id: str, seconds: float | None = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&t={int(seconds)}s" if seconds is not None else base


def fetch_metadata(video_id: str) -> dict:
    """Title and channel via YouTube's public oEmbed endpoint. Metadata only, never used for summaries."""
    try:
        r = httpx.get("https://www.youtube.com/oembed", params={"url": watch_url(video_id), "format": "json"}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {"title": d.get("title"), "channel": d.get("author_name")}
    except httpx.HTTPError:
        pass
    return {"title": None, "channel": None}


@dataclass
class Seg:
    start: float
    duration: float
    text: str


class CaptionsUnavailable(Exception):
    pass


def fetch_captions(video_id: str) -> tuple[list[Seg], str]:
    """Existing YouTube captions, English preferred. Raises CaptionsUnavailable with a readable reason."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled,
                                                VideoUnavailable)
    api = YouTubeTranscriptApi()
    try:
        tl = api.list(video_id)
        try:
            tr = tl.find_transcript(["en", "en-US", "en-GB"])
        except NoTranscriptFound:
            tr = next(iter(tl))
        fetched = tr.fetch()
    except TranscriptsDisabled:
        raise CaptionsUnavailable("Captions are turned off for this video.")
    except VideoUnavailable:
        raise CaptionsUnavailable("YouTube says this video is unavailable.")
    except (NoTranscriptFound, StopIteration):
        raise CaptionsUnavailable("This video has no captions we can read.")
    except CouldNotRetrieveTranscript as e:
        raise CaptionsUnavailable(f"YouTube did not return captions ({type(e).__name__}).")
    except Exception as e:  # network problems, rate limits
        raise CaptionsUnavailable(f"Could not reach YouTube captions ({type(e).__name__}).")
    segs = [Seg(s.start, s.duration, clean(s.text)) for s in fetched.snippets if clean(s.text)]
    if not segs:
        raise CaptionsUnavailable("The captions were empty.")
    kind = "auto-generated" if fetched.is_generated else "creator-provided"
    return segs, f"Existing YouTube captions ({kind}, {fetched.language})"


def clean(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[(music|applause|♪+)\]", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"


def _secs(m: re.Match) -> float:
    h, mi, s, ms = m.groups()[:4]
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (int(ms.ljust(3, "0")) / 1000 if ms else 0)


def parse_transcript_text(raw: str) -> tuple[list[Seg], bool]:
    """Parse pasted/uploaded transcripts. Understands SRT/VTT cues and 'm:ss text' lines (YouTube's transcript
    panel). Returns (segments, has_real_timestamps). Without timestamps, text is split into ~25-word pieces
    with no times (start = -1), and the UI says timestamps are unknown."""
    raw = raw.replace("\r\n", "\n").strip()
    segs: list[Seg] = []
    cue = re.compile(rf"^{_TS}\s*-->\s*{_TS}")
    lines = raw.split("\n")
    i = 0
    if any(cue.match(l.strip()) for l in lines[:40]):
        while i < len(lines):
            m = cue.match(lines[i].strip())
            if m:
                g = m.groups()
                start = int(g[0] or 0) * 3600 + int(g[1]) * 60 + int(g[2]) + (int((g[3] or "0").ljust(3, "0")) / 1000)
                end = int(g[4] or 0) * 3600 + int(g[5]) * 60 + int(g[6]) + (int((g[7] or "0").ljust(3, "0")) / 1000)
                i += 1
                body = []
                while i < len(lines) and lines[i].strip() and not cue.match(lines[i].strip()):
                    body.append(lines[i].strip())
                    i += 1
                text = clean(" ".join(body))
                if text and (not segs or segs[-1].text != text):
                    segs.append(Seg(start, max(0.5, end - start), text))
            else:
                i += 1
        return segs, True

    stamp_line = re.compile(rf"^\s*{_TS}\s*(.*)$")
    stamped = [stamp_line.match(l) for l in lines if l.strip()]
    if stamped and sum(1 for m in stamped if m) >= max(2, len(stamped) // 3):
        pending_start: float | None = None
        for l in lines:
            if not l.strip():
                continue
            m = stamp_line.match(l)
            if m:
                pending_start = _secs(m)
                rest = clean(m.group(5))
                if rest:
                    segs.append(Seg(pending_start, 0, rest))
                    pending_start = None
            elif pending_start is not None:
                segs.append(Seg(pending_start, 0, clean(l)))
                pending_start = None
            elif segs:
                segs[-1].text += " " + clean(l)
        for a, b in zip(segs, segs[1:]):
            a.duration = max(0.5, b.start - a.start)
        if segs:
            segs[-1].duration = 5
        return segs, True

    words = clean(raw).split()
    for j in range(0, len(words), 25):
        segs.append(Seg(-1, 0, " ".join(words[j:j + 25])))
    return segs, False


def fmt_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "time unknown"
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
