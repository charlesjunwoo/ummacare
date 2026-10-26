"""Deterministic orchestration around the agent's skills: video stages, caching, frames, connections."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic_ai.messages import BinaryContent

from . import ai, db, media, records
from .agent import (DocDeps, doc_agent, BriefDeps, ConnectDeps, ConnectionsOut, MedDeps, TranscriptDeps, VideoAnalysisOut, brief_agent,
                    connect_agent, image_agent, med_agent, moment_agent)
from .config import CONNECTION_VERSION, MAX_MOMENTS, MAX_TRANSCRIPT_CHARS, MEDIA_DIR, MODEL_NAME, PROCESSING_VERSION
from .youtube import Seg, fmt_time


def sha(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


KIND_PROMPT = {"youtube": "YouTube video transcript", "video_file": "video transcript", "article": "web article",
               "reddit": "Reddit community thread (post and comments)", "image": "text read from a photo or clipping"}


def cache_get(key: str) -> Any | None:
    r = db.row("SELECT value FROM ai_cache WHERE key=?", (key,))
    return json.loads(r["value"]) if r else None


def cache_put(key: str, kind: str, value: Any) -> None:
    db.execute("INSERT OR REPLACE INTO ai_cache(key,kind,value,created_at) VALUES(?,?,?,?)", (key, kind, json.dumps(value), db.now()))


def log_cache_hit(workflow: str) -> dict:
    return ai.log_usage(workflow, None, time.perf_counter(), ok=True, cache_hit=True)


# --- stage 1: transcript ----------------------------------------------------------------

def store_transcript(video_id: int, segs: list[Seg], source: str, note: str) -> dict:
    text = "\n".join(f"{s.start:.2f}|{s.text}" for s in segs)
    h = sha(text)
    flags = ai.scan_untrusted(" ".join(s.text for s in segs))
    with db.tx() as c:
        old = c.execute("SELECT transcript_hash FROM videos WHERE id=?", (video_id,)).fetchone()
        if old and old["transcript_hash"] != h:   # source content changed: old analysis is invalid
            _drop_analysis(c, video_id)
        c.execute("DELETE FROM segments WHERE video_id=?", (video_id,))
        c.executemany("INSERT INTO segments(video_id, idx, start, duration, text) VALUES(?,?,?,?,?)",
                      [(video_id, i, s.start, s.duration, s.text) for i, s in enumerate(segs)])
        c.execute("""UPDATE videos SET transcript_source=?, transcript_note=?, transcript_hash=?, status='transcript_ready',
                     status_detail=?, injection_flags=?, updated_at=? WHERE id=?""",
                  (source, note, h, f"{len(segs)} transcript segments ready", json.dumps(flags), db.now(), video_id))
    if flags:
        ai.record_safety_event("instruction_like_text", f"video:{video_id}", f"{len(flags)} instruction-like sentence(s) flagged in transcript")
    records.index_video_passages(video_id)
    return {"segments": len(segs), "injection_flags": flags}


def _drop_analysis(c, video_id: int) -> None:
    mids = [r["id"] for r in c.execute("SELECT id FROM moments WHERE video_id=?", (video_id,)).fetchall()]
    for mid in mids:
        c.execute("DELETE FROM connections WHERE (from_kind='moment' AND from_id=?) OR (to_kind='moment' AND to_id=?)", (mid, mid))
        c.execute("DELETE FROM record_fts WHERE kind='moment' AND ref_id=?", (mid,))
    c.execute("DELETE FROM moments WHERE video_id=?", (video_id,))
    c.execute("UPDATE videos SET summary=NULL, analysis_version=NULL WHERE id=?", (video_id,))


# --- stage 2: important moments (AI, cached) -------------------------------------------------

def transcript_for_prompt(video_id: int) -> tuple[str, int, bool]:
    segs = db.rows("SELECT idx, start, text FROM segments WHERE video_id=? ORDER BY idx", (video_id,))
    lines, total, truncated = [], 0, False
    for s in segs:
        line = f"[{s['idx']} @{fmt_time(s['start'])}] {ai.neutralize(s['text'])}"
        if total + len(line) > MAX_TRANSCRIPT_CHARS:
            truncated = True
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines), len(lines), truncated


async def analyze_video(video_id: int, force: bool = False) -> dict:
    v = db.row("SELECT * FROM videos WHERE id=?", (video_id,))
    if not v or not v["transcript_hash"]:
        raise ValueError("No transcript yet. A summary is never generated from a title alone.")
    key = sha("moments", v["kind"], v["transcript_hash"], PROCESSING_VERSION, MODEL_NAME)
    existing = db.row("SELECT COUNT(*) AS n FROM moments WHERE video_id=? AND analysis_version=?", (video_id, key[:16]))
    if existing["n"] and not force:
        log_cache_hit("analyze_video")
        return {"cached": True, "usage": None}
    out_json = None if force else cache_get(key)
    usage = None
    truncated = False
    if out_json is None:
        text, n, truncated = transcript_for_prompt(video_id)
        prompt = (f"Source type: {KIND_PROMPT.get(v['kind'], 'video transcript')}\n"
                  f"Title (metadata only, not evidence): {v['title'] or 'unknown'}\n"
                  f"Text source: {v['transcript_note']}\n"
                  + ("NOTE: transcript truncated to fit limits; only the part shown is analyzed.\n" if truncated else "")
                  + ai.wrap_untrusted("transcript", text))
        out, usage, _ = await ai.run(moment_agent, prompt, "analyze_video", deps=TranscriptDeps(n_segments=n))
        out_json = out.model_dump()
        cache_put(key, "moments", out_json)
    else:
        log_cache_hit("analyze_video")
    out = VideoAnalysisOut.model_validate(out_json)
    segs = {s["idx"]: s for s in db.rows("SELECT * FROM segments WHERE video_id=?", (video_id,))}
    with db.tx() as c:
        _drop_analysis(c, video_id)
        for pos, m in enumerate(out.moments[:MAX_MOMENTS]):
            first, last = segs[m.first_segment], segs[m.last_segment]
            excerpt = " ".join(segs[i]["text"] for i in range(m.first_segment, m.last_segment + 1) if i in segs)
            c.execute("""INSERT INTO moments(video_id, position, heading, explanation, kind, claims, topics, seg_start, seg_end,
                         start, end, excerpt, frame_status, frame_note, analysis_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (video_id, pos, m.heading, m.explanation, m.kind, json.dumps(m.claims), json.dumps(m.topics),
                       m.first_segment, m.last_segment, first["start"], last["start"] + last["duration"], excerpt[:2500],
                       "unavailable" if v["kind"] in ("youtube", "video_file") else "none",
                       (media.YOUTUBE_FRAME_POLICY if not v["media_path"] else "Not captured yet.") if v["kind"] in ("youtube", "video_file") else None, key[:16]))
        c.execute("UPDATE videos SET summary=?, analysis_version=?, status='analyzed', status_detail=?, updated_at=? WHERE id=?",
                  (out.overall_summary, key[:16], f"{len(out.moments[:MAX_MOMENTS])} key moments" + (" (transcript truncated)" if truncated else ""),
                   db.now(), video_id))
    for m in db.rows("SELECT id FROM moments WHERE video_id=?", (video_id,)):
        records.index_moment(m["id"])
    return {"cached": usage is None, "usage": usage, "quality_note": out.transcript_quality_note}


# --- stage 3: frames (deterministic, separate media capability) --------------------------------

def capture_frames(video_id: int) -> dict:
    v = db.row("SELECT * FROM videos WHERE id=?", (video_id,))
    ms = db.rows("SELECT * FROM moments WHERE video_id=? ORDER BY position", (video_id,))
    if v["kind"] not in ("youtube", "video_file"):
        for m in ms:
            db.execute("UPDATE moments SET frame_status='none', frame_path=NULL, frame_note=NULL WHERE id=?", (m["id"],))
        return {"captured": 0, "reason": "not a video", "not_video": True}
    if not v["media_path"]:
        for m in ms:
            db.execute("UPDATE moments SET frame_status='unavailable', frame_path=NULL, frame_note=? WHERE id=?",
                       (media.YOUTUBE_FRAME_POLICY, m["id"]))
        return {"captured": 0, "reason": media.YOUTUBE_FRAME_POLICY}
    path = MEDIA_DIR / v["media_path"]
    duration = media.probe_duration(path)
    if not media.ffmpeg_available() or duration is None:
        note = "Frame unavailable: the uploaded file could not be read as video (ffmpeg/ffprobe)."
        for m in ms:
            db.execute("UPDATE moments SET frame_status='unavailable', frame_path=NULL, frame_note=? WHERE id=?", (note, m["id"]))
        return {"captured": 0, "reason": note}
    captured = 0
    for m in ms:
        rel, t, note = media.capture_frame(path, video_id, m["id"], m["start"], m["end"], duration)
        db.execute("UPDATE moments SET frame_status=?, frame_path=?, frame_time=?, frame_note=? WHERE id=?",
                   ("captured" if rel else "unavailable", rel, t, note, m["id"]))
        captured += bool(rel)
    return {"captured": captured, "of": len(ms)}


# --- stage 4: connections (AI, cached on content of everything it reads) -------------------------

def _candidate_block(cands: dict[str, dict]) -> str:
    items = []
    for ref, d in cands.items():
        items.append({"id": ref, "type": d.get("label"), "date": d.get("date"), "title": d.get("title"),
                      "text": ai.neutralize((d.get("text") or "")[:600])} | ({"excerpt": ai.neutralize(d["excerpt"][:400])} if d.get("excerpt") else {}))
    return ai.wrap_untrusted("earlier_records", json.dumps(items, ensure_ascii=False, indent=0))


def _ref_block(refs: dict[str, dict]) -> str:
    return json.dumps([{"passage_id": r["id"], "publisher": r["publisher"], "section": r["section"], "text": r["text"][:1500]}
                       for r in refs.values()], ensure_ascii=False, indent=0)


def _save_connections(out: ConnectionsOut, item_map: dict[str, tuple[str, int]], key: str) -> int:
    froms = set(item_map.values())
    with db.tx() as c:
        kept = {(r["from_kind"], r["from_id"], r["to_kind"], r["to_id"]) for r in
                c.execute("SELECT * FROM connections WHERE status IN ('dismissed','corrected')").fetchall()}
        for fk, fid in froms:
            c.execute("DELETE FROM connections WHERE from_kind=? AND from_id=? AND status='active'", (fk, fid))
            if fk == "moment":
                c.execute("DELETE FROM claim_checks WHERE moment_id=?", (fid,))
        n = 0
        for x in out.connections:
            fk, fid = item_map[x.new_item]
            tk, tid = x.record_ref.split(":")
            if (fk, fid, tk, int(tid)) in kept or (fk, fid) == (tk, int(tid)):
                continue  # the user already dismissed/corrected this pair; don't resurrect it
            c.execute("""INSERT INTO connections(from_kind, from_id, to_kind, to_id, relation, new_information, why_related,
                         uncertain, clinician_question, interpretation, cache_key, created_at, updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (fk, fid, tk, int(tid), x.relation, x.new_information, x.why_related, x.uncertain,
                       x.clinician_question, x.interpretation, key[:16], db.now(), db.now()))
            n += 1
        for k in out.claim_checks:
            fk, fid = item_map[k.new_item]
            if fk == "moment":
                c.execute("INSERT INTO claim_checks(moment_id, claim, passage_id, verdict, explanation, created_at) VALUES(?,?,?,?,?,?)",
                          (fid, k.claim, k.passage_id, k.verdict, k.explanation, db.now()))
    return n


def _fingerprint(cands: dict[str, dict]) -> list:
    return sorted((ref, (d.get("title"), d.get("text"), d.get("date"))) for ref, d in cands.items())


async def connect_video(video_id: int, force: bool = False) -> dict:
    ms = db.rows("SELECT * FROM moments WHERE video_id=? ORDER BY position", (video_id,))
    if not ms:
        raise ValueError("Analyze the transcript first.")
    own = {("moment", m["id"]) for m in ms}
    cands: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    new_lines, item_map = [], {}
    for i, m in enumerate(ms, 1):
        tag = f"M{i}"
        item_map[tag] = ("moment", m["id"])
        claims, topics = json.loads(m["claims"]), json.loads(m["topics"])
        q = f"{m['heading']} {' '.join(topics)} {' '.join(claims)}"
        for h in db.search_records(q, kinds=("note", "symptom", "moment", "question"), limit=5, exclude=own):
            d = records.describe(h["kind"], int(h["ref_id"]))
            if d:
                cands[f"{d['kind']}:{d['id']}"] = d
        for r in db.search_references(" ".join(claims + topics) or m["heading"], limit=2):
            refs[r["id"]] = r
        new_lines.append({"id": tag, "heading": m["heading"], "timestamp": fmt_time(m["start"]),
                          "speaker_says": m["explanation"], "claims": claims, "excerpt": ai.neutralize(m["excerpt"][:700])})
    key = sha("connect_video", CONNECTION_VERSION, MODEL_NAME, new_lines, _fingerprint(cands), sorted(refs))
    cached = None if force else cache_get(key)
    usage = None
    if cached is None:
        kind = db.row("SELECT kind FROM videos WHERE id=?", (video_id,))["kind"]
        prompt = (f"NEW MATERIAL — key takeaways from a {KIND_PROMPT.get(kind, 'video transcript')} she just added"
                  + (" (community experiences: anecdotes, not evidence)" if kind == "reddit" else "") + ":\n"
                  + ai.wrap_untrusted("video_moments", json.dumps(new_lines, ensure_ascii=False, indent=0))
                  + "\n\nCANDIDATE EARLIER RECORDS (from keyword search; may be irrelevant):\n" + _candidate_block(cands)
                  + "\n\nREFERENCE PASSAGES:\n" + _ref_block(refs))
        out, usage, _ = await ai.run(connect_agent, prompt, "connect_video",
                                     deps=ConnectDeps(set(item_map), set(cands), set(refs)))
        cache_put(key, "connections", out.model_dump())
    else:
        out = ConnectionsOut.model_validate(cached)
        log_cache_hit("connect_video")
    n = _save_connections(out, item_map, key)
    return {"connections": n, "claim_checks": len(out.claim_checks), "candidates": len(cands), "cached": usage is None, "usage": usage}


async def connect_record(kind: str, ref_id: int) -> dict:
    """Incremental: relate ONE new note/symptom to existing videos and records, without reprocessing videos."""
    d = records.describe(kind, ref_id)
    if not d:
        raise ValueError("Record not found")
    q = f"{d['title']} {d.get('text', '')}"
    cands = {}
    for h in db.search_records(q, kinds=("moment", "note", "symptom"), limit=8, exclude={(kind, ref_id)}):
        c = records.describe(h["kind"], int(h["ref_id"]))
        if c:
            cands[f"{c['kind']}:{c['id']}"] = c
    if not cands:
        return {"connections": 0, "candidates": 0, "cached": True, "usage": None, "message": "No related earlier records found by search."}
    refs = {r["id"]: r for r in db.search_references(q, limit=2)}
    new = {"id": "NEW", "type": d["label"], "date": d.get("date"), "title": d["title"], "text": ai.neutralize((d.get("text") or "")[:1500])}
    key = sha("connect_record", CONNECTION_VERSION, MODEL_NAME, new, _fingerprint(cands), sorted(refs))
    cached = cache_get(key)
    usage = None
    if cached is None:
        prompt = ("NEW MATERIAL — a record she just saved:\n" + ai.wrap_untrusted("new_record", json.dumps(new, ensure_ascii=False))
                  + "\n\nCANDIDATE EARLIER RECORDS AND VIDEO MOMENTS (from keyword search; may be irrelevant):\n"
                  + _candidate_block(cands) + "\n\nREFERENCE PASSAGES:\n" + _ref_block(refs)
                  + ("\n\nAlso write new_item_summary." if kind == "note" else "\n\nSet new_item_summary to null."))
        out, usage, _ = await ai.run(connect_agent, prompt, "connect_record", deps=ConnectDeps({"NEW"}, set(cands), set(refs)))
        cache_put(key, "connections", out.model_dump())
    else:
        out = ConnectionsOut.model_validate(cached)
        log_cache_hit("connect_record")
    n = _save_connections(out, {"NEW": (kind, ref_id)}, key)
    if kind == "note" and out.new_item_summary:
        db.execute("UPDATE notes SET ai_summary=? WHERE id=?", (out.new_item_summary, ref_id))
        records.index_note(ref_id)
    return {"connections": n, "candidates": len(cands), "cached": usage is None, "usage": usage}


# --- other skills ---------------------------------------------------------------------------

async def read_note_image(image_bytes: bytes, media_type: str) -> tuple[dict, dict]:
    out, usage, _ = await ai.run(image_agent, ["Transcribe this note. Remember: [illegible] instead of guessing.",
                                               BinaryContent(data=image_bytes, media_type=media_type)], "read_note_image")
    d = out.model_dump()
    d["flags"] = ai.scan_untrusted(out.text)
    return d, usage


async def extract_medication(source: str) -> tuple[dict, dict]:
    out, usage, _ = await ai.run(med_agent, ai.wrap_untrusted("medication_label_text", source), "extract_medication",
                                 deps=MedDeps(source=source))
    return out.model_dump(), usage


async def draft_brief(items: dict[str, dict]) -> tuple[dict, dict]:
    payload = [{"id": ref, "type": d.get("label"), "date": d.get("date"), "title": d.get("title"), "text": (d.get("text") or "")[:500]}
               for ref, d in items.items()]
    out, usage, _ = await ai.run(brief_agent, "SELECTED ITEMS:\n" + ai.wrap_untrusted("selected_items", json.dumps(payload, ensure_ascii=False)),
                                 "draft_brief", deps=BriefDeps(refs=set(items)))
    return out.model_dump(), usage


async def read_document(doc_id: int) -> tuple[dict, dict]:
    """Copy a medical document into fields for review. PDFs with a text layer are read as text (and copied values are
    verified against it); scans and photos are sent as images. Nothing is saved until she reviews it."""
    d = db.row("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not d:
        raise ValueError("Document not found")
    path = MEDIA_DIR / d["file_path"]
    if d["mime"] == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:10]).strip()
        if len(text) > 120:
            text = text[:20_000]
            out, usage, _ = await ai.run(doc_agent, ai.wrap_untrusted("medical_document_text", ai.neutralize(text)),
                                         "read_document", deps=DocDeps(source_text=text))
            return {**out.model_dump(), "read_by": "pdf_text", "flags": ai.scan_untrusted(text)}, usage
        images = [BinaryContent(data=img.data, media_type="image/png" if img.name.lower().endswith(".png") else "image/jpeg")
                  for pg in reader.pages[:3] for img in pg.images][:3]
        if not images:
            raise ValueError("This PDF has no readable text or page images. Try uploading a photo of each page instead.")
        out, usage, _ = await ai.run(doc_agent, ["Copy this scanned document. [illegible] instead of guessing.", *images],
                                     "read_document", deps=DocDeps(source_text=None))
        return {**out.model_dump(), "read_by": "ai_image", "flags": ai.scan_untrusted(out.text)}, usage
    out, usage, _ = await ai.run(doc_agent, ["Copy this document photo. [illegible] instead of guessing.",
                                             BinaryContent(data=path.read_bytes(), media_type=d["mime"])],
                                 "read_document", deps=DocDeps(source_text=None))
    return {**out.model_dump(), "read_by": "ai_image", "flags": ai.scan_untrusted(out.text)}, usage
