"""UmmaCare API. Local, single-user. Every data change proposed by AI waits in pending_actions until the
user approves it through these endpoints; the agent itself has no route to apply changes."""

from __future__ import annotations

import html
import json
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

import re

from . import ai, care, db, media, pipeline, records, seed, sources
from .agent import ChatDeps, chat_agent
from .config import (DAILY_BUDGET_USD, MAX_CHAT_CHARS, MAX_UPLOAD_MB, MEDIA_DIR, MODEL_NAME, REPO_ROOT,
                     ai_key_present)
from .youtube import (CaptionsUnavailable, extract_video_id, fetch_captions, fetch_metadata, fmt_time,
                      parse_transcript_text, watch_url)

app = FastAPI(title="UmmaCare API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


@app.on_event("startup")
def startup() -> None:
    db.init()
    if db.get_setting("demo_initialized") is None:   # first run: load clearly labeled synthetic records
        seed.load_demo()
        db.set_setting("demo_initialized", "yes")


@app.exception_handler(ai.AIBlocked)
async def _blocked(_: Request, e: ai.AIBlocked):
    return JSONResponse({"detail": str(e), "kind": "ai_blocked"}, status_code=403)


@app.exception_handler(UsageLimitExceeded)
async def _limit(_: Request, e: UsageLimitExceeded):
    ai.record_safety_event("usage_limit", "agent_run", str(e)[:200])
    return JSONResponse({"detail": f"Stopped to protect the budget: {e}", "kind": "limit"}, status_code=429)


@app.exception_handler(ModelHTTPError)
async def _model_err(_: Request, e: ModelHTTPError):
    if "content_filter" in str(e.body):   # the provider's own jailbreak/safety filter, an extra layer
        ai.record_safety_event("provider_content_filter", "model_provider", "Request refused by the provider's safety filter.")
        return JSONResponse({"detail": "The AI provider's safety filter refused this request (it looked like an attempt to "
                             "override the assistant's rules). Nothing was changed.", "kind": "content_filter"}, status_code=422)
    return JSONResponse({"detail": f"The AI service returned an error ({e.status_code}). Nothing was saved. Try again later.",
                         "kind": "model_error"}, status_code=502)


@app.exception_handler(UnexpectedModelBehavior)
async def _model_bad(_: Request, e: UnexpectedModelBehavior):
    return JSONResponse({"detail": "The AI answer failed validation after retries, so nothing was saved.", "kind": "invalid_output"},
                        status_code=502)


@app.exception_handler(ValueError)
async def _value(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


def _404(what: str):
    raise HTTPException(404, f"{what} not found")


# ============================================================ status, consent, privacy controls

@app.get("/api/status")
def status():
    return {"consent": ai.consent_given(), "key_present": ai_key_present(), "model": MODEL_NAME,
            "spent_today_usd": round(ai.spent_today(), 5), "daily_budget_usd": DAILY_BUDGET_USD,
            "ffmpeg": media.ffmpeg_available(),
            "demo_loaded": bool(db.row("SELECT 1 AS x FROM notes WHERE is_demo=1 LIMIT 1")),
            "pending_actions": db.row("SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'")["n"]}


class Consent(BaseModel):
    agree: bool


@app.post("/api/consent")
def consent(c: Consent):
    db.set_setting("ai_consent", "yes" if c.agree else "no")
    db.set_setting("ai_consent_at", db.now())
    return status()


@app.post("/api/demo/{action}")
def demo(action: Literal["load", "remove"]):
    return seed.load_demo() if action == "load" else seed.remove_demo()


PERSONAL_TABLES = ["videos", "segments", "moments", "notes", "note_revisions", "symptoms", "connections", "claim_checks",
                   "questions", "medications", "med_schedules", "dose_logs", "appointments", "pending_actions", "documents", "orders"]


@app.get("/api/export")
def export_all():
    data = {t: db.rows(f"SELECT * FROM {t}") for t in PERSONAL_TABLES}
    data["_exported_at"] = db.now()
    return Response(json.dumps(data, indent=1, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=ummacare-export.json"})


class DeleteAll(BaseModel):
    confirm: str


@app.post("/api/delete-all")
def delete_all(d: DeleteAll):
    if d.confirm != "DELETE MY DATA":
        raise HTTPException(400, "Type DELETE MY DATA to confirm.")
    with db.tx() as c:
        for t in reversed(PERSONAL_TABLES):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM record_fts")
        c.execute("DELETE FROM ai_cache")
    for p in MEDIA_DIR.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    db.set_setting("demo_initialized", "yes")
    return {"deleted": True}


@app.get("/api/usage")
def usage():
    rows_ = db.rows("SELECT * FROM usage_log ORDER BY id DESC LIMIT 300")
    agg = db.rows("""SELECT workflow, COUNT(*) AS runs, SUM(cache_hit) AS cache_hits, AVG(input_tokens) AS avg_in,
                     AVG(cached_tokens) AS avg_cached, AVG(output_tokens) AS avg_out, AVG(latency_ms) AS avg_ms, SUM(cost_usd) AS cost
                     FROM usage_log WHERE ok=1 GROUP BY workflow""")
    return {"rows": rows_, "by_workflow": agg}


@app.get("/api/safety-events")
def safety_events():
    return db.rows("SELECT * FROM safety_events ORDER BY id DESC LIMIT 100")


# ============================================================ dashboard

def _video_card(v: dict) -> dict:
    ms = db.rows("SELECT id, heading, start, frame_status, frame_path FROM moments WHERE video_id=? ORDER BY position", (v["id"],))
    frame = next((m["frame_path"] for m in ms if m["frame_status"] == "captured"), None)
    n_conn = db.row(f"""SELECT COUNT(*) AS n FROM connections WHERE status!='dismissed' AND from_kind='moment'
                        AND from_id IN ({','.join(str(m['id']) for m in ms) or '0'})""")["n"]
    return {**{k: v[k] for k in ("id", "youtube_id", "title", "channel", "status", "status_detail", "transcript_source",
                                 "transcript_note", "summary", "created_at", "media_path", "kind", "source_url", "site", "image_path")},
            "moments": [{"id": m["id"], "heading": m["heading"], "time": fmt_time(m["start"])} for m in ms],
            "frame": frame, "frames_captured": sum(m["frame_status"] == "captured" for m in ms), "connections": n_conn,
            "url": watch_url(v["youtube_id"]) if v["youtube_id"] else None}


def _connection_view(c: dict) -> dict | None:
    a, b = records.describe(c["from_kind"], c["from_id"]), records.describe(c["to_kind"], c["to_id"])
    if not a or not b:
        return None
    return {**c, "new": a, "earlier": b}


@app.get("/api/dashboard")
def dashboard():
    vids = db.rows("SELECT * FROM videos ORDER BY created_at DESC LIMIT 6")
    conns = [x for c in db.rows("SELECT * FROM connections WHERE status!='dismissed' ORDER BY created_at DESC, id LIMIT 8")
             if (x := _connection_view(c))]
    today = date.today()
    return {"videos": [_video_card(v) for v in vids], "connections": conns[:6],
            "questions": db.rows("SELECT * FROM questions WHERE status='open' ORDER BY created_at DESC LIMIT 8"),
            "doses": care.doses_for_day(today),
            "appointments": db.rows("""SELECT * FROM appointments WHERE status IN ('requested','confirmed','draft_request')
                                       AND (starts_at IS NULL OR starts_at >= ?) ORDER BY starts_at LIMIT 4""", (today.isoformat(),)),
            "recent_symptoms": db.rows("SELECT * FROM symptoms ORDER BY occurred_on DESC, id DESC LIMIT 4"),
            "pending": db.rows("SELECT * FROM pending_actions WHERE status='pending' ORDER BY id DESC")}


# ============================================================ videos

class NewVideo(BaseModel):
    url: str = Field(max_length=500)


@app.post("/api/videos")
def add_video(body: NewVideo):
    vid = extract_video_id(body.url)
    if not vid:
        raise HTTPException(400, "That doesn't look like a YouTube link. Try one like https://www.youtube.com/watch?v=… or https://youtu.be/…")
    existing = db.row("SELECT * FROM videos WHERE youtube_id=?", (vid,))
    if existing:
        return {"video": _video_card(existing), "stages": [{"stage": "already_added", "ok": True,
                "detail": "You already added this video. Its saved transcript and analysis are reused."}]}
    meta = fetch_metadata(vid)
    ts = db.now()
    video_id = db.execute("""INSERT INTO videos(youtube_id,url,title,channel,status,transcript_source,created_at,updated_at)
                             VALUES(?,?,?,?,?,?,?,?)""", (vid, watch_url(vid), meta["title"], meta["channel"], "new", "none", ts, ts))
    stages = [{"stage": "link", "ok": True, "detail": f"Video ID {vid}" + (f" · “{meta['title']}”" if meta["title"] else " · title unavailable")}]
    try:
        segs, note = fetch_captions(vid)
        info = pipeline.store_transcript(video_id, segs, "youtube_captions", note)
        stages.append({"stage": "captions", "ok": True, "detail": f"{note}: {info['segments']} timed lines retrieved. "
                       "These are YouTube's existing captions, not a new transcription."})
        if info["injection_flags"]:
            stages.append({"stage": "safety", "ok": True, "warn": True,
                           "detail": f"{len(info['injection_flags'])} instruction-like sentence(s) found in the transcript. They are treated as content only."})
    except CaptionsUnavailable as e:
        db.execute("UPDATE videos SET status='needs_transcript', status_detail=? WHERE id=?", (str(e), video_id))
        stages.append({"stage": "captions", "ok": False, "detail": f"{e} You can paste the transcript or upload a caption file. "
                       "No summary will be made without a transcript."})
    return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (video_id,))), "stages": stages}


# ---------------------------------------------------------------- discovery: articles, threads, photos

class SourceLink(BaseModel):
    url: str = Field(max_length=1000)


def _new_source(kind: str, title: str, url: str | None = None, site: str | None = None, image_path: str | None = None,
                status: str = "needs_transcript", detail: str | None = None) -> int:
    ts = db.now()
    return db.execute("""INSERT INTO videos(kind,title,url,source_url,site,image_path,status,status_detail,transcript_source,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (kind, title[:200], url, url, site, image_path, status, detail, "none", ts, ts))


@app.post("/api/sources/link")
def add_source_link(body: SourceLink):
    url = body.url.strip()
    if extract_video_id(url):
        return add_video(NewVideo(url=url))
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Paste a full link that starts with https://")
    existing = db.row("SELECT * FROM videos WHERE source_url=?", (url,))
    if existing:
        return {"video": _video_card(existing), "stages": [{"stage": "already_added", "ok": True, "detail": "Already in Discovery."}]}
    if sources.is_reddit(url):
        sub = re.search(r"/r/([^/]+)", url)
        vid = _new_source("reddit", f"r/{sub.group(1)} thread" if sub else "Reddit thread", url, "reddit.com", detail=
                          "Reddit doesn't let apps read threads without a registered account, so UmmaCare doesn't fetch it. "
                          "Open the thread, select the post and comments, copy, and paste them here (or upload a screenshot).")
        return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))),
                "stages": [{"stage": "text", "ok": False, "detail": "Reddit threads need to be pasted in."}]}
    try:
        title, site, segs = sources.fetch_article(url)
    except sources.SourceUnavailable as e:
        vid = _new_source("article", sources.site_of(url), url, sources.site_of(url), detail=f"{e} Paste the article text instead.")
        return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))),
                "stages": [{"stage": "text", "ok": False, "detail": str(e)}]}
    vid = _new_source("article", title, url, site)
    info = pipeline.store_transcript(vid, segs, "article_page", f"Article text read from {site}")
    return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))),
            "stages": [{"stage": "text", "ok": True, "detail": f"{info['segments']} paragraphs read from {site}"}]
            + ([{"stage": "safety", "ok": True, "warn": True, "detail": "Instruction-like text flagged"}] if info["injection_flags"] else [])}


class SourceText(BaseModel):
    kind: Literal["reddit", "article", "video_file"] = "reddit"
    title: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    text: str = Field(min_length=40, max_length=200_000)
    video_id: int | None = None      # paste into an existing entry


@app.post("/api/sources/text")
def add_source_text(b: SourceText):
    vid = b.video_id
    if vid:
        v = db.row("SELECT * FROM videos WHERE id=?", (vid,)) or _404("Source")
        kind = v["kind"]
    else:
        kind = b.kind
        vid = _new_source(kind, b.title, b.url, sources.site_of(b.url) if b.url else None)
    if kind == "reddit":
        segs, note = sources.clean_thread(b.text), "Thread pasted by you (usernames removed)"
    elif kind == "article":
        segs, note = sources.split_text(b.text), "Article text pasted by you"
    else:
        segs, timed = parse_transcript_text(b.text)
        note = "Transcript pasted by you" + ("" if timed else " · no timestamps")
    if len(segs) < 2:
        raise HTTPException(400, "Not enough readable text. Paste the full post and comments.")
    info = pipeline.store_transcript(vid, segs, "pasted", note)
    return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))), **info}


@app.post("/api/sources/image")
async def add_source_image(file: UploadFile = File(...), title: str = Form("")):
    ext = Path(file.filename or "").suffix.lower()
    types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    if ext not in types:
        raise HTTPException(400, "Upload a JPG, PNG, or WEBP photo.")
    raw = await file.read(10_000_001)
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Image too large (10 MB max).")
    extracted, usage_rec = await pipeline.read_note_image(raw, types[ext])   # AI read first: nothing stored if it fails
    (MEDIA_DIR / "sources").mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (MEDIA_DIR / "sources" / name).write_bytes(raw)
    vid = _new_source("image", title or extracted["suggested_title"], image_path=f"sources/{name}")
    segs = sources.split_text(extracted["text"])
    if len(segs) < 2:
        return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))), "segments": len(segs),
                "warning": "Very little readable text was found in this photo."}
    info = pipeline.store_transcript(vid, segs, "image_read", f"Text read from your photo by AI ({extracted['illegible_sections']} part(s) illegible)")
    return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,))), "usage": usage_rec, **info}


@app.get("/api/sources/communities")
def communities():
    return sources.REDDIT_COMMUNITIES


@app.post("/api/videos/manual")
def add_manual_video(title: str = Form(...)):
    ts = db.now()
    vid = db.execute("INSERT INTO videos(kind,title,status,transcript_source,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     ("video_file", title[:200], "needs_transcript", "none", ts, ts))
    return {"video": _video_card(db.row("SELECT * FROM videos WHERE id=?", (vid,)))}


@app.get("/api/videos")
def list_videos():
    return [_video_card(v) for v in db.rows("SELECT * FROM videos ORDER BY created_at DESC")]


@app.get("/api/videos/{video_id}")
def get_video(video_id: int):
    v = db.row("SELECT * FROM videos WHERE id=?", (video_id,)) or _404("Video")
    ms = db.rows("SELECT * FROM moments WHERE video_id=? ORDER BY position", (video_id,))
    out_ms = []
    for m in ms:
        conns = [x for c in db.rows("SELECT * FROM connections WHERE from_kind='moment' AND from_id=? ORDER BY status, id", (m["id"],))
                 if (x := _connection_view(c))]
        incoming = [x for c in db.rows("SELECT * FROM connections WHERE to_kind='moment' AND to_id=? AND status!='dismissed'", (m["id"],))
                    if (x := _connection_view(c))]
        checks = db.rows("SELECT * FROM claim_checks WHERE moment_id=?", (m["id"],))
        for k in checks:
            k["reference"] = db.row("SELECT * FROM references_ WHERE id=?", (k["passage_id"],)) if k["passage_id"] else None
        out_ms.append({**m, "claims": json.loads(m["claims"]), "topics": json.loads(m["topics"]), "time": fmt_time(m["start"]),
                       "link": records.video_link(v, m["start"]), "connections": conns, "incoming": incoming, "claim_checks": checks})
    segs = db.rows("SELECT idx, start, text FROM segments WHERE video_id=? ORDER BY idx", (video_id,))
    return {**_video_card(v), "injection_flags": json.loads(v["injection_flags"] or "[]"), "media_note": v["media_note"],
            "moments_full": out_ms, "segments": segs, "frame_policy": media.YOUTUBE_FRAME_POLICY}


@app.post("/api/videos/{video_id}/transcript")
async def set_transcript(video_id: int, text: str = Form(""), file: UploadFile | None = File(None)):
    db.row("SELECT id FROM videos WHERE id=?", (video_id,)) or _404("Video")
    source, note = "pasted", "Transcript pasted by you"
    if file is not None and file.filename:
        raw = (await file.read(2_000_001))
        if len(raw) > 2_000_000:
            raise HTTPException(413, "Transcript file is too large (2 MB max).")
        text = raw.decode("utf-8", errors="replace")
        source, note = "uploaded_file", f"Transcript file uploaded by you ({file.filename})"
    if len(text.strip()) < 40:
        raise HTTPException(400, "The transcript is empty or too short to analyze.")
    segs, timed = parse_transcript_text(text)
    if not timed:
        note += " · no timestamps found, so timestamp links are unavailable"
    info = pipeline.store_transcript(video_id, segs, source, note)
    return {"ok": True, "timed": timed, **info}


@app.post("/api/videos/{video_id}/media")
async def upload_media(video_id: int, file: UploadFile = File(...)):
    v = db.row("SELECT * FROM videos WHERE id=?", (video_id,)) or _404("Video")
    ext = Path(file.filename or "video.mp4").suffix.lower()
    if ext not in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
        raise HTTPException(400, "Please upload a video file (.mp4, .mov, .m4v, .webm, .mkv).")
    dest_dir = MEDIA_DIR / f"video_{video_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{ext}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                f.close(); dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Video is larger than {MAX_UPLOAD_MB} MB.")
            f.write(chunk)
    if media.probe_duration(dest) is None:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "That file could not be read as a video.")
    db.execute("UPDATE videos SET media_path=?, media_note=? WHERE id=?",
               (str(dest.relative_to(MEDIA_DIR)), f"Video file uploaded by you ({file.filename})", video_id))
    result = pipeline.capture_frames(video_id) if db.row("SELECT 1 AS x FROM moments WHERE video_id=?", (video_id,)) else {"captured": 0}
    return {"ok": True, **result}


@app.post("/api/videos/{video_id}/analyze")
async def analyze(video_id: int, force: bool = False):
    r = await pipeline.analyze_video(video_id, force=force)
    frames = pipeline.capture_frames(video_id)
    return {**r, "frames": frames}


@app.post("/api/videos/{video_id}/frames")
def frames(video_id: int):
    return pipeline.capture_frames(video_id)


@app.post("/api/videos/{video_id}/connect")
async def connect(video_id: int, force: bool = False):
    return await pipeline.connect_video(video_id, force=force)


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int):
    with db.tx() as c:
        pipeline._drop_analysis(c, video_id)
        c.execute("DELETE FROM record_fts WHERE kind='passage' AND ref_id IN (SELECT id FROM segments WHERE video_id=?)", (video_id,))
        c.execute("DELETE FROM videos WHERE id=?", (video_id,))
    shutil.rmtree(MEDIA_DIR / f"video_{video_id}", ignore_errors=True)
    return {"deleted": True}


@app.post("/api/moments/{moment_id}/save")
def save_moment(moment_id: int, saved: bool = True):
    db.execute("UPDATE moments SET saved=? WHERE id=?", (int(saved), moment_id))
    return {"saved": saved}


# ============================================================ notes

CATEGORIES = Literal["symptom_observation", "video_or_article", "diet_lifestyle", "doctor_instruction", "personal_question"]


class NoteIn(BaseModel):
    category: CATEGORIES
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
    source: Literal["typed", "pasted", "text_upload", "markdown_upload", "image"] = "typed"
    source_detail: str | None = None
    recorded_on: str | None = None
    image_ref: str | None = None          # from /api/notes/image, the preserved original
    extracted_text: str | None = None     # what the AI read, kept so corrections are visible


@app.get("/api/notes")
def list_notes(category: str | None = None):
    q = "SELECT * FROM notes" + (" WHERE category=?" if category else "") + " ORDER BY recorded_on DESC, id DESC"
    return db.rows(q, (category,) if category else ())


@app.post("/api/notes")
def create_note(n: NoteIn):
    ts = db.now()
    image_path = None
    if n.image_ref:
        p = MEDIA_DIR / "notes" / Path(n.image_ref).name
        if not p.exists():
            raise HTTPException(400, "Original image not found; upload it again.")
        image_path = f"notes/{p.name}"
    original = n.extracted_text if (n.source == "image" and n.extracted_text) else n.text
    nid = db.execute("""INSERT INTO notes(category,title,original_text,current_text,source,source_detail,image_path,recorded_on,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (n.category, n.title, original, n.text, n.source, n.source_detail, image_path,
                      n.recorded_on or date.today().isoformat(), ts, ts))
    if n.source == "image" and n.extracted_text and n.extracted_text != n.text:
        db.execute("INSERT INTO note_revisions(note_id,text,edited_at,reason) VALUES(?,?,?,?)",
                   (nid, n.text, ts, "Your corrections to the AI-read text before saving"))
    records.index_note(nid)
    flags = ai.scan_untrusted(n.text)
    if flags:
        ai.record_safety_event("instruction_like_text", f"note:{nid}", f"{len(flags)} instruction-like sentence(s) in imported note")
    return {"id": nid, "flags": flags}


@app.post("/api/notes/upload")
async def upload_note_file(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".txt", ".md", ".markdown"):
        raise HTTPException(400, "Upload a .txt or .md file. For photos of notes, use 'Photo of a note'.")
    raw = await file.read(500_001)
    if len(raw) > 500_000:
        raise HTTPException(413, "File too large (500 KB max).")
    text = raw.decode("utf-8", errors="replace")
    return {"text": text, "source": "markdown_upload" if ext != ".txt" else "text_upload", "source_detail": file.filename,
            "title": Path(file.filename).stem.replace("_", " ")[:120], "flags": ai.scan_untrusted(text)}


@app.post("/api/notes/image")
async def read_note_image(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    if ext not in types:
        raise HTTPException(400, "Upload a JPG, PNG, or WEBP photo.")
    raw = await file.read(10_000_001)
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Image too large (10 MB max).")
    (MEDIA_DIR / "notes").mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (MEDIA_DIR / "notes" / name).write_bytes(raw)        # the original is preserved as-is
    extracted, usage_rec = await pipeline.read_note_image(raw, types[ext])
    return {"image_ref": name, "image_url": f"/media/notes/{name}", "extracted": extracted, "usage": usage_rec}


@app.get("/api/notes/{note_id}")
def get_note(note_id: int):
    n = db.row("SELECT * FROM notes WHERE id=?", (note_id,)) or _404("Note")
    n["revisions"] = db.rows("SELECT * FROM note_revisions WHERE note_id=? ORDER BY id", (note_id,))
    n["connections"] = [x for c in db.rows("""SELECT * FROM connections WHERE (from_kind='note' AND from_id=?) OR (to_kind='note' AND to_id=?)
                                             ORDER BY id DESC""", (note_id, note_id)) if (x := _connection_view(c))]
    return n


class NoteEdit(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    title: str | None = None
    category: CATEGORIES | None = None
    reason: str | None = None


@app.put("/api/notes/{note_id}")
def edit_note(note_id: int, e: NoteEdit):
    n = db.row("SELECT * FROM notes WHERE id=?", (note_id,)) or _404("Note")
    ts = db.now()
    db.execute("INSERT INTO note_revisions(note_id,text,edited_at,reason) VALUES(?,?,?,?)", (note_id, e.text, ts, e.reason or "Edited"))
    db.execute("UPDATE notes SET current_text=?, title=?, category=?, updated_at=?, ai_summary=NULL WHERE id=?",
               (e.text, e.title or n["title"], e.category or n["category"], ts, note_id))
    records.index_note(note_id)
    return get_note(note_id)


@app.post("/api/notes/{note_id}/connect")
async def connect_note(note_id: int):
    return await pipeline.connect_record("note", note_id)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    n = db.row("SELECT * FROM notes WHERE id=?", (note_id,)) or _404("Note")
    db.execute("DELETE FROM connections WHERE (from_kind='note' AND from_id=?) OR (to_kind='note' AND to_id=?)", (note_id, note_id))
    db.execute("DELETE FROM notes WHERE id=?", (note_id,))
    db.unindex_record("note", note_id)
    if n["image_path"]:
        (MEDIA_DIR / n["image_path"]).unlink(missing_ok=True)
    return {"deleted": True}


# ============================================================ symptoms

class SymptomIn(BaseModel):
    symptom: str = Field(min_length=1, max_length=80)
    occurred_on: str | None = None
    severity: int = Field(ge=0, le=10)
    duration: str | None = Field(default=None, max_length=80)
    context: str | None = Field(default=None, max_length=200)
    details: str | None = Field(default=None, max_length=4000)


@app.get("/api/symptoms")
def list_symptoms():
    return db.rows("""SELECT s.*, (SELECT COUNT(*) FROM connections c WHERE c.status!='dismissed' AND
                      ((c.from_kind='symptom' AND c.from_id=s.id) OR (c.to_kind='symptom' AND c.to_id=s.id))) AS related
                      FROM symptoms s ORDER BY occurred_on DESC, id DESC""")


@app.get("/api/symptoms/{sid}/related")
def symptom_related(sid: int):
    """Connections for one symptom entry, shown wherever the entry appears."""
    cs = db.rows("""SELECT * FROM connections WHERE (from_kind='symptom' AND from_id=?) OR (to_kind='symptom' AND to_id=?)
                    ORDER BY status='dismissed', id DESC""", (sid, sid))
    out = []
    for c in cs:
        v = _connection_view(c)
        if v:
            if c["to_kind"] == "symptom" and c["to_id"] == sid:   # show the OTHER record as "your record"
                v = {**v, "new": v["earlier"], "earlier": v["new"]}
            out.append(v)
    return out


@app.post("/api/symptoms")
def add_symptom(s: SymptomIn):
    sid = db.execute("INSERT INTO symptoms(symptom,occurred_on,severity,duration,context,details,created_at) VALUES(?,?,?,?,?,?,?)",
                     (s.symptom.strip().lower(), s.occurred_on or date.today().isoformat(), s.severity, s.duration, s.context, s.details, db.now()))
    records.index_symptom(sid)
    return {"id": sid}


@app.delete("/api/symptoms/{sid}")
def delete_symptom(sid: int):
    db.execute("DELETE FROM connections WHERE (from_kind='symptom' AND from_id=?) OR (to_kind='symptom' AND to_id=?)", (sid, sid))
    db.execute("DELETE FROM symptoms WHERE id=?", (sid,))
    db.unindex_record("symptom", sid)
    return {"deleted": True}


@app.post("/api/symptoms/{sid}/connect")
async def connect_symptom(sid: int):
    return await pipeline.connect_record("symptom", sid)


# ============================================================ connections

@app.get("/api/connections")
def list_connections(status: str = "active"):
    q = "SELECT * FROM connections" + ("" if status == "all" else " WHERE status=?") + " ORDER BY id DESC"
    return [x for c in db.rows(q, () if status == "all" else (status,)) if (x := _connection_view(c))]


class Correction(BaseModel):
    action: Literal["dismiss", "correct", "restore"]
    relation: Literal["repeats", "adds_detail", "conflicts", "related"] | None = None
    note: str | None = Field(default=None, max_length=1000)


@app.post("/api/connections/{cid}")
def fix_connection(cid: int, c: Correction):
    db.row("SELECT id FROM connections WHERE id=?", (cid,)) or _404("Connection")
    if c.action == "dismiss":
        db.execute("UPDATE connections SET status='dismissed', user_correction=?, updated_at=? WHERE id=?", (c.note, db.now(), cid))
    elif c.action == "restore":
        db.execute("UPDATE connections SET status='active', updated_at=? WHERE id=?", (db.now(), cid))
    else:
        db.execute("UPDATE connections SET status='corrected', relation=COALESCE(?, relation), user_correction=?, updated_at=? WHERE id=?",
                   (c.relation, c.note, db.now(), cid))
    return _connection_view(db.row("SELECT * FROM connections WHERE id=?", (cid,)))


# ============================================================ questions

class QuestionIn(BaseModel):
    text: str = Field(min_length=3, max_length=600)
    origin_kind: str | None = None
    origin_id: int | None = None


@app.get("/api/questions")
def list_questions():
    return db.rows("SELECT * FROM questions ORDER BY status='open' DESC, created_at DESC")


@app.post("/api/questions")
def add_question(q: QuestionIn):
    ts = db.now()
    qid = db.execute("INSERT INTO questions(text,origin_kind,origin_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (q.text, q.origin_kind or "manual", q.origin_id, "open", ts, ts))
    records.index_question(qid)
    return {"id": qid}


class QuestionPatch(BaseModel):
    status: Literal["open", "asked", "answered"] | None = None
    answer: str | None = Field(default=None, max_length=4000)


@app.patch("/api/questions/{qid}")
def patch_question(qid: int, p: QuestionPatch):
    q = db.row("SELECT * FROM questions WHERE id=?", (qid,)) or _404("Question")
    db.execute("UPDATE questions SET status=?, answer=?, updated_at=? WHERE id=?",
               (p.status or q["status"], p.answer if p.answer is not None else q["answer"], db.now(), qid))
    records.index_question(qid)
    return db.row("SELECT * FROM questions WHERE id=?", (qid,))


@app.delete("/api/questions/{qid}")
def delete_question(qid: int):
    db.execute("DELETE FROM questions WHERE id=?", (qid,))
    db.unindex_record("question", qid)
    return {"deleted": True}


# ============================================================ search (no AI) and chat (AI)

@app.get("/api/search")
def search(q: str):
    hits = db.search_records(q, kinds=("note", "symptom", "question", "moment", "passage", "document"), limit=20)
    out = []
    for h in hits:
        d = records.describe(h["kind"], int(h["ref_id"]))
        if d:
            out.append({**d, "snippet": h["snip"]})
    refs = db.search_references(q, limit=3)
    return {"results": out, "references": refs}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=6)


def _resolve(ref: str) -> dict | None:
    if ":" in ref:
        kind, i = ref.split(":", 1)
        return records.describe(kind, int(i)) if i.isdigit() else None
    r = db.row("SELECT * FROM references_ WHERE id=?", (ref,))
    return r and {"kind": "reference", **r}


@app.post("/api/chat")
async def chat(body: ChatIn):
    flags = ai.scan_untrusted(body.message)
    hist = "\n".join(f"Earlier Q: {h.get('q', '')[:300]}\nEarlier A: {h.get('a', '')[:500]}" for h in body.history[-3:])
    prompt = (f"Today is {date.today().isoformat()}.\n" + (f"Recent conversation (context only):\n{hist}\n\n" if hist else "")
              + f"Her question: {body.message}")
    deps = ChatDeps()
    out, usage_rec, result = await ai.run(chat_agent, prompt, "chat", deps=deps, tool_calls=8)
    tools_used = [p.tool_name for m in result.all_messages() for p in getattr(m, "parts", []) if getattr(p, "part_kind", "") == "tool-call"]
    return {"answer": out.answer, "interpretation": out.interpretation,
            "personal_records": [d for r in out.personal_records if (d := _resolve(r))],
            "video_passages": [d for r in out.video_passages if (d := _resolve(r))],
            "references": [d for r in out.references if (d := _resolve(r))],
            "pending": [db.row("SELECT * FROM pending_actions WHERE id=?", (p,)) for p in out.pending_actions],
            "tools_used": tools_used, "usage": usage_rec, "input_flags": flags}


# ============================================================ pending actions (human review queue)

@app.get("/api/pending")
def pending():
    return db.rows("SELECT * FROM pending_actions ORDER BY status='pending' DESC, id DESC LIMIT 50")


class Decision(BaseModel):
    approve: bool
    edits: dict[str, Any] | None = None


@app.post("/api/pending/{pid}")
def decide(pid: int, d: Decision):
    p = db.row("SELECT * FROM pending_actions WHERE id=?", (pid,)) or _404("Pending action")
    if p["status"] != "pending":
        raise HTTPException(409, f"Already {p['status']}.")
    result: dict[str, Any] = {}
    if d.approve:
        payload = {**json.loads(p["payload"]), **(d.edits or {})}
        if p["kind"] == "save_question":
            result = add_question(QuestionIn(text=payload["text"], origin_kind="chat"))
        elif p["kind"] == "appointment_request":
            ts = db.now()
            text = draft_request_text(payload)
            aid = db.execute("""INSERT INTO appointments(title,clinician,status,booking_link,request_text,notes,created_by,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?)""",
                             (f"Visit with {payload['clinician']}", payload["clinician"], "draft_request", payload.get("booking_link") or None,
                              text, payload.get("reason"), "chat_agent (approved by you)", ts, ts))
            result = {"appointment_id": aid}
        elif p["kind"] == "order_request":
            ts = db.now()
            oid = db.execute("""INSERT INTO orders(item,kind,quantity,store_link,notes,status,created_by,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?)""", (payload["item"], payload["kind"], payload.get("quantity"),
                                payload.get("store_link") or None, payload.get("notes"), "draft", "chat_agent (approved by you)", ts, ts))
            result = {"order_id": oid}
        else:
            raise HTTPException(400, "Unknown action kind.")
    db.execute("UPDATE pending_actions SET status=?, decided_at=? WHERE id=?", ("approved" if d.approve else "rejected", db.now(), pid))
    return {"status": "approved" if d.approve else "rejected", **result}


def draft_request_text(p: dict) -> str:
    return (f"Hello, I would like to request an appointment with {p.get('clinician')}.\n"
            f"Reason: {p.get('reason')}\n" + (f"Times that work for me: {p['preferred_times']}\n" if p.get("preferred_times") else "")
            + "Please let me know what times are available. Thank you.")


# ============================================================ medications & doses

class MedIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instruction_text: str = Field(min_length=1, max_length=2000)
    dose_text: str = Field(min_length=1, max_length=80)
    times: list[str] = Field(min_length=1, max_length=8)
    days: str = "daily"
    starts_on: str | None = None
    source: Literal["typed", "ai_extracted_reviewed"] = "typed"
    reviewed: bool = False


def _check_times(times: list[str]) -> None:
    for t in times:
        try:
            datetime.strptime(t, "%H:%M")
        except ValueError:
            raise HTTPException(400, f"Time '{t}' must look like 07:30.")


@app.get("/api/medications")
def list_meds():
    meds = db.rows("SELECT * FROM medications ORDER BY active DESC, name")
    for m in meds:
        m["schedules"] = db.rows("SELECT * FROM med_schedules WHERE medication_id=? ORDER BY starts_on DESC", (m["id"],))
        for s in m["schedules"]:
            s["times"] = json.loads(s["times"])
    return meds


@app.post("/api/medications")
def add_med(m: MedIn):
    if m.source == "ai_extracted_reviewed" and not m.reviewed:
        raise HTTPException(400, "AI-extracted instructions must be reviewed (tick the review box) before saving.")
    _check_times(m.times)
    mid = db.execute("INSERT INTO medications(name,instruction_text,source,created_at) VALUES(?,?,?,?)",
                     (m.name, m.instruction_text, m.source, db.now()))
    db.execute("""INSERT INTO med_schedules(medication_id,dose_text,times,days,starts_on,change_reason,created_at)
                  VALUES(?,?,?,?,?,?,?)""", (mid, m.dose_text, json.dumps(m.times), m.days, m.starts_on or date.today().isoformat(),
                                             "First entry", db.now()))
    return {"id": mid}


class MedExtractIn(BaseModel):
    text: str = Field(min_length=5, max_length=3000)


@app.post("/api/medications/extract")
async def extract_med(body: MedExtractIn):
    out, usage_rec = await pipeline.extract_medication(body.text)
    return {"proposal": out, "usage": usage_rec, "needs_review": True}


class ScheduleChange(BaseModel):
    dose_text: str = Field(min_length=1, max_length=80)
    times: list[str] = Field(min_length=1, max_length=8)
    days: str = "daily"
    starts_on: str
    reason: str = Field(min_length=1, max_length=300)


@app.post("/api/medications/{mid}/schedule")
def change_sched(mid: int, s: ScheduleChange):
    _check_times(s.times)
    return {"schedule_id": care.change_schedule(mid, s.dose_text, s.times, s.days, s.starts_on, s.reason)}


@app.post("/api/medications/{mid}/stop")
def stop_med(mid: int):
    db.execute("UPDATE medications SET active=0 WHERE id=?", (mid,))
    db.execute("UPDATE med_schedules SET ends_on=? WHERE medication_id=? AND ends_on IS NULL", (date.today().isoformat(), mid))
    return {"stopped": True}


@app.get("/api/medications/{mid}/calendar.ics")
def med_ics(mid: int):
    return Response(care.medication_ics(mid), media_type="text/calendar",
                    headers={"Content-Disposition": f"attachment; filename=medication-{mid}.ics"})


@app.get("/api/doses")
def doses(day: str | None = None, days: int = 1):
    start = date.fromisoformat(day) if day else date.today()
    return [{"date": (start - timedelta(days=i)).isoformat(), "doses": care.doses_for_day(start - timedelta(days=i))} for i in range(max(1, min(days, 14)))]


class DoseIn(BaseModel):
    schedule_id: int
    due_at: str
    status: Literal["taken", "skipped", "unrecorded"]


@app.post("/api/doses")
def log_dose(d: DoseIn):
    care.log_dose(d.schedule_id, d.due_at, d.status)
    return {"ok": True}


# ============================================================ appointments

class ApptIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    clinician: str | None = None
    location: str | None = None
    starts_at: str | None = None
    duration_min: int = 30
    status: Literal["draft_request", "requested", "confirmed", "completed", "cancelled"] = "requested"
    booking_link: str | None = None
    notes: str | None = None


@app.get("/api/appointments")
def list_appts():
    return db.rows("SELECT * FROM appointments ORDER BY COALESCE(starts_at,'9999') ")


@app.post("/api/appointments")
def add_appt(a: ApptIn):
    if a.booking_link and not a.booking_link.startswith("https://"):
        raise HTTPException(400, "Booking links must start with https://")
    ts = db.now()
    aid = db.execute("""INSERT INTO appointments(title,clinician,location,starts_at,duration_min,status,booking_link,notes,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""", (a.title, a.clinician, a.location, a.starts_at, a.duration_min, a.status,
                                                         a.booking_link, a.notes, ts, ts))
    return {"id": aid}


class ApptPatch(BaseModel):
    status: Literal["draft_request", "requested", "confirmed", "completed", "cancelled"] | None = None
    starts_at: str | None = None
    notes: str | None = None


@app.patch("/api/appointments/{aid}")
def patch_appt(aid: int, p: ApptPatch):
    a = db.row("SELECT * FROM appointments WHERE id=?", (aid,)) or _404("Appointment")
    db.execute("UPDATE appointments SET status=?, starts_at=?, notes=?, updated_at=? WHERE id=?",
               (p.status or a["status"], p.starts_at or a["starts_at"], p.notes if p.notes is not None else a["notes"], db.now(), aid))
    return db.row("SELECT * FROM appointments WHERE id=?", (aid,))


@app.delete("/api/appointments/{aid}")
def delete_appt(aid: int):
    db.execute("DELETE FROM appointments WHERE id=?", (aid,))
    return {"deleted": True}


@app.get("/api/appointments/{aid}/request-draft")
def appt_draft(aid: int):
    a = db.row("SELECT * FROM appointments WHERE id=?", (aid,)) or _404("Appointment")
    return {"text": a["request_text"] or draft_request_text({"clinician": a["clinician"] or a["title"], "reason": a["notes"] or a["title"]}),
            "booking_link": a["booking_link"]}


@app.get("/api/appointments.ics")
def appts_ics(ids: str | None = None):
    id_list = [int(x) for x in ids.split(",")] if ids else None
    return Response(care.appointment_ics(id_list), media_type="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=ummacare-appointments.ics"})


# ============================================================ appointment brief

@app.get("/api/brief/candidates")
def brief_candidates():
    since = (date.today() - timedelta(days=60)).isoformat()
    saved = db.rows("""SELECT m.id FROM moments m WHERE m.saved=1 ORDER BY m.id DESC""")
    conflicts = db.rows("SELECT * FROM connections WHERE relation='conflicts' AND status!='dismissed' ORDER BY id DESC")
    return {"symptoms": [records.describe("symptom", s["id"]) for s in db.rows("SELECT id FROM symptoms WHERE occurred_on>=? ORDER BY occurred_on DESC", (since,))],
            "moments": [records.describe("moment", m["id"]) for m in saved],
            "notes": [records.describe("note", n["id"]) for n in db.rows("SELECT id FROM notes ORDER BY recorded_on DESC LIMIT 30")],
            "documents": [records.describe("document", d["id"]) for d in db.rows("SELECT id FROM documents WHERE status='reviewed' ORDER BY document_date DESC LIMIT 20")],
            "questions": [records.describe("question", q["id"]) for q in db.rows("SELECT id FROM questions WHERE status='open'")],
            "conflicts": [x for c in conflicts if (x := _connection_view(c))],
            "appointments": db.rows("SELECT * FROM appointments WHERE status IN ('requested','confirmed') ORDER BY starts_at")}


class BriefIn(BaseModel):
    refs: list[str] = Field(min_length=1, max_length=40)
    appointment_id: int | None = None
    use_ai: bool = False


@app.post("/api/brief")
async def make_brief(b: BriefIn):
    items = {r: d for r in b.refs if (d := _resolve(r))}
    draft, usage_rec = (await pipeline.draft_brief(items)) if b.use_ai else (None, None)
    appt = db.row("SELECT * FROM appointments WHERE id=?", (b.appointment_id,)) if b.appointment_id else None
    return {"html": render_brief(items, draft, appt), "draft": draft, "usage": usage_rec}


def render_brief(items: dict[str, dict], draft: dict | None, appt: dict | None) -> str:
    e = lambda s: html.escape(str(s or ""))
    by = lambda k: [d for d in items.values() if d["kind"] == k]
    sec = []
    if draft:
        pts = "".join(f"<li>{e(p['point'])} <span class='ref'>[{e(', '.join(p['refs']))}]</span></li>" for p in draft["points"])
        sec.append(f"<h2>What I want to discuss <span class='tag'>AI-drafted from the items below — please check</span></h2>"
                   f"<p>{e(draft['opening'])}</p><ul>{pts}</ul>")
    if s := by("symptom"):
        sec.append("<h2>Symptoms I recorded</h2><table><tr><th>Date</th><th>Entry</th><th>Notes</th></tr>" + "".join(
            f"<tr><td>{e(x['date'])}</td><td>{e(x['title'])} <span class='ref'>[symptom:{x['id']}]</span></td><td>{e(x['text'])}</td></tr>" for x in s)
                   + "</table><p class='small'>These are my own journal entries. They do not by themselves show whether my condition or a treatment is changing.</p>")
    if m := by("moment"):
        sec.append("<h2>Video claims I'd like to check</h2><ul>" + "".join(
            f"<li><b>{e(x['title'])}</b> — {e(x['label'])}<br>{e(x['text'])}<br><span class='small'>{e(x.get('link'))}</span> <span class='ref'>[moment:{x['id']}]</span></li>" for x in m) + "</ul>")
    if n := by("note"):
        sec.append("<h2>My notes</h2><ul>" + "".join(
            f"<li><b>{e(x['title'])}</b> ({e(x['label'])}, {e(x['date'])})<br>{e(x['text'])} <span class='ref'>[note:{x['id']}]</span></li>" for x in n) + "</ul>")
    if q := by("question"):
        sec.append("<h2>My questions</h2><ol>" + "".join(f"<li>{e(x['title'])}<br><span class='line'>Answer: ______________________________</span></li>" for x in q) + "</ol>")
    if dd := by("document"):
        sec.append("<h2>My medical documents</h2><ul>" + "".join(
            f"<li><b>{e(x['title'])}</b> ({e(x['date'])}{', ' + e(x.get('provider')) if x.get('provider') else ''})<br><span class='small'>{e(x['text'][:400])}</span> <span class='ref'>[document:{x['id']}]</span></li>" for x in dd)
                   + "</ul><p class='small'>Values copied as written in the documents; I have not interpreted them.</p>")
    if r := by("reference"):
        sec.append("<h2>Reference passages</h2><ul>" + "".join(f"<li>{e(x['publisher'])}, “{e(x['section'])}” ({e(x['url'])}, reviewed {e(x['reviewed'])})</li>" for x in r) + "</ul>")
    head = f"<p><b>Appointment:</b> {e(appt['title'])} — {e(appt['clinician'])} — {e(appt['starts_at'])} ({e(appt['status'])})</p>" if appt else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Appointment brief</title><style>
body{{font-family:Georgia,serif;font-size:15px;line-height:1.5;color:#222;max-width:760px;margin:30px auto;padding:0 20px}}
h1{{font-size:26px;margin-bottom:0}} h2{{font-size:19px;border-bottom:2px solid #5e7f64;padding-bottom:3px;margin-top:26px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:5px 7px;text-align:left;vertical-align:top}}
.ref{{color:#777;font-size:12px}} .small{{color:#555;font-size:13px}} .tag{{font-size:12px;background:#eef3ec;padding:2px 6px;border-radius:4px;font-weight:normal}}
.line{{color:#999}} footer{{margin-top:30px;font-size:12px;color:#666;border-top:1px solid #ccc;padding-top:8px}}
</style></head><body><h1>My appointment brief</h1><p class="small">Prepared {date.today().isoformat()} with UmmaCare.</p>{head}{''.join(sec)}
<footer>This brief collects my own records, things videos claimed, and my questions. It is not medical advice and does not
diagnose anything. Notes labeled “doctor's instruction” are what I wrote down, not verified guidance.</footer></body></html>"""


# ============================================================ medical documents

DOC_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@app.get("/api/documents")
def list_documents():
    docs = db.rows("SELECT * FROM documents ORDER BY COALESCE(document_date, created_at) DESC")
    for d in docs:
        d["results"] = json.loads(d["results"] or "[]")
    return docs


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in DOC_MIME:
        raise HTTPException(400, "Upload a PDF or a photo (JPG, PNG, WEBP).")
    raw = await file.read(25_000_001)
    if len(raw) > 25_000_000:
        raise HTTPException(413, "File too large (25 MB max).")
    (MEDIA_DIR / "documents").mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (MEDIA_DIR / "documents" / name).write_bytes(raw)       # the original is kept unchanged
    ts = db.now()
    did = db.execute("""INSERT INTO documents(title,file_path,mime,original_name,status,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?)""", (Path(file.filename).stem[:120], f"documents/{name}", DOC_MIME[ext], file.filename, "uploaded", ts, ts))
    return get_document(did)


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int):
    d = db.row("SELECT * FROM documents WHERE id=?", (doc_id,)) or _404("Document")
    d["results"] = json.loads(d["results"] or "[]")
    d["url"] = f"/media/{d['file_path']}"
    return d


@app.post("/api/documents/{doc_id}/read")
async def read_document(doc_id: int):
    proposal, usage_rec = await pipeline.read_document(doc_id)
    return {"proposal": proposal, "usage": usage_rec, "needs_review": True}


class DocResultIn(BaseModel):
    test: str = Field(max_length=120)
    value: str = Field(max_length=60)
    unit: str = Field(default="", max_length=30)
    reference_range: str = Field(default="", max_length=60)
    flag_as_written: str = Field(default="", max_length=20)


class DocSave(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    doc_type: Literal["lab_result", "visit_summary", "imaging_report", "prescription", "other"] = "other"
    document_date: str | None = None
    provider: str | None = Field(default=None, max_length=160)
    extracted_text: str | None = Field(default=None, max_length=60_000)
    results: list[DocResultIn] = Field(default_factory=list, max_length=60)
    read_by: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    reviewed: bool = False


@app.put("/api/documents/{doc_id}")
def save_document(doc_id: int, d: DocSave):
    db.row("SELECT id FROM documents WHERE id=?", (doc_id,)) or _404("Document")
    if d.read_by in ("ai_image", "ai_text", "pdf_text") and not d.reviewed:
        raise HTTPException(400, "Please check the copied details against the document (tick the review box) before saving.")
    db.execute("""UPDATE documents SET title=?, doc_type=?, document_date=?, provider=?, extracted_text=?, results=?, read_by=?,
                  notes=?, status='reviewed', updated_at=? WHERE id=?""",
               (d.title, d.doc_type, d.document_date or None, d.provider, d.extracted_text,
                json.dumps([r.model_dump() for r in d.results]), d.read_by or "none", d.notes, db.now(), doc_id))
    records.index_document(doc_id)
    return get_document(doc_id)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    d = db.row("SELECT * FROM documents WHERE id=?", (doc_id,)) or _404("Document")
    db.execute("DELETE FROM connections WHERE (from_kind='document' AND from_id=?) OR (to_kind='document' AND to_id=?)", (doc_id, doc_id))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.unindex_record("document", doc_id)
    (MEDIA_DIR / d["file_path"]).unlink(missing_ok=True)
    return {"deleted": True}


# ============================================================ order requests (never purchases)

class OrderIn(BaseModel):
    item: str = Field(min_length=1, max_length=160)
    kind: Literal["prescription_refill", "supplement", "other"] = "other"
    quantity: str | None = Field(default=None, max_length=60)
    store_link: str | None = None
    notes: str | None = Field(default=None, max_length=300)


@app.get("/api/orders")
def list_orders():
    return db.rows("SELECT * FROM orders ORDER BY status IN ('received','cancelled'), updated_at DESC")


@app.post("/api/orders")
def add_order(o: OrderIn):
    if o.store_link and not o.store_link.startswith("https://"):
        raise HTTPException(400, "Store links must start with https://")
    ts = db.now()
    oid = db.execute("""INSERT INTO orders(item,kind,quantity,store_link,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                     (o.item, o.kind, o.quantity, o.store_link, o.notes, "draft", ts, ts))
    return {"id": oid}


class OrderPatch(BaseModel):
    status: Literal["draft", "placed", "received", "cancelled"]


@app.patch("/api/orders/{oid}")
def patch_order(oid: int, p: OrderPatch):
    db.row("SELECT id FROM orders WHERE id=?", (oid,)) or _404("Order")
    db.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (p.status, db.now(), oid))
    return db.row("SELECT * FROM orders WHERE id=?", (oid,))


# ============================================================ log calendar

@app.get("/api/log/month")
def log_month(month: str):
    """Per-day markers for a month (YYYY-MM): appointments, symptoms, doctor's notes, dose completion."""
    start = date.fromisoformat(month + "-01")
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days: dict[str, dict] = {}
    def day(d: str) -> dict:
        return days.setdefault(d, {"appointments": 0, "symptoms": 0, "doctor_notes": 0, "notes": 0, "doses_due": 0, "doses_taken": 0})
    for a in db.rows("SELECT substr(starts_at,1,10) d FROM appointments WHERE starts_at>=? AND starts_at<? AND status!='cancelled'", (start.isoformat(), nxt.isoformat())):
        day(a["d"])["appointments"] += 1
    for s_ in db.rows("SELECT occurred_on d FROM symptoms WHERE occurred_on>=? AND occurred_on<?", (start.isoformat(), nxt.isoformat())):
        day(s_["d"])["symptoms"] += 1
    for n in db.rows("SELECT recorded_on d, category FROM notes WHERE recorded_on>=? AND recorded_on<?", (start.isoformat(), nxt.isoformat())):
        day(n["d"])["doctor_notes" if n["category"] == "doctor_instruction" else "notes"] += 1
    d = start
    while d < nxt and d <= date.today():
        doses = care.doses_for_day(d)
        if doses:
            x = day(d.isoformat())
            x["doses_due"] = len(doses)
            x["doses_taken"] = sum(1 for z in doses if z["status"] == "taken")
        d += timedelta(days=1)
    return days


@app.get("/api/log/day")
def log_day(day: str):
    d = date.fromisoformat(day)
    return {"date": day,
            "appointments": db.rows("SELECT * FROM appointments WHERE substr(starts_at,1,10)=? ORDER BY starts_at", (day,)),
            "doses": care.doses_for_day(d),
            "symptoms": db.rows("SELECT * FROM symptoms WHERE occurred_on=? ORDER BY id", (day,)),
            "notes": db.rows("SELECT id, title, category, current_text, source FROM notes WHERE recorded_on=? ORDER BY id", (day,)),
            "documents": db.rows("SELECT id, title, doc_type FROM documents WHERE document_date=?", (day,))}


# ============================================================ built frontend (optional single-port mode)

DIST = REPO_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
