"""Uniform views of personal records and video passages, for search, citations, and connections."""

from __future__ import annotations

import json
from typing import Any

from . import db
from .youtube import fmt_time, watch_url

CATEGORY_LABELS = {
    "symptom_observation": "Symptom observation",
    "video_or_article": "Video or article note",
    "diet_lifestyle": "Diet or lifestyle note",
    "doctor_instruction": "Doctor's instruction (as you recorded it)",
    "personal_question": "Personal question",
}


def video_link(video: dict, seconds: float | None) -> str | None:
    if video.get("youtube_id") and seconds is not None and seconds >= 0:
        return watch_url(video["youtube_id"], seconds)
    if video.get("youtube_id"):
        return watch_url(video["youtube_id"])
    return None


def describe(kind: str, ref_id: int) -> dict[str, Any] | None:
    """A citation-ready summary of one record. Returns None if it no longer exists."""
    if kind == "note":
        n = db.row("SELECT * FROM notes WHERE id=?", (ref_id,))
        if not n:
            return None
        return dict(kind="note", id=n["id"], title=n["title"], date=n["recorded_on"],
                    label=CATEGORY_LABELS.get(n["category"], n["category"]), category=n["category"],
                    text=n["current_text"], provenance=f"{n['source']}" + (f" · {n['source_detail']}" if n["source_detail"] else ""),
                    is_demo=bool(n["is_demo"]))
    if kind == "symptom":
        s = db.row("SELECT * FROM symptoms WHERE id=?", (ref_id,))
        if not s:
            return None
        bits = [f"severity {s['severity']}/10"] + ([f"lasted {s['duration']}"] if s["duration"] else []) + \
               ([f"context: {s['context']}"] if s["context"] else [])
        return dict(kind="symptom", id=s["id"], title=f"{s['symptom'].capitalize()} ({', '.join(bits)})",
                    date=s["occurred_on"], label="Symptom entry", text=s["details"] or "", is_demo=bool(s["is_demo"]))
    if kind == "moment":
        m = db.row("SELECT m.*, v.title AS vtitle, v.youtube_id, v.channel, v.kind AS vkind FROM moments m JOIN videos v ON v.id=m.video_id WHERE m.id=?", (ref_id,))
        if not m:
            return None
        at = f" at {fmt_time(m['start'])}" if m["start"] is not None and m["start"] >= 0 else ""
        return dict(kind="moment", id=m["id"], video_id=m["video_id"], title=m["heading"], source_kind=m["vkind"],
                    label=f"{KIND_LABELS.get(m['vkind'], 'Video')}: {m['vtitle'] or 'Untitled'}{at}",
                    date=None, text=m["explanation"], excerpt=m["excerpt"], start=m["start"],
                    link=video_link({"youtube_id": m["youtube_id"]}, m["start"]),
                    claims=json.loads(m["claims"]))
    if kind == "passage":
        s = db.row("SELECT s.*, v.title AS vtitle, v.youtube_id, v.kind AS vkind FROM segments s JOIN videos v ON v.id=s.video_id WHERE s.id=?", (ref_id,))
        if not s:
            return None
        chunk = db.rows("SELECT text FROM segments WHERE video_id=? AND idx>=? AND idx<? ORDER BY idx",
                        (s["video_id"], s["idx"], s["idx"] + PASSAGE_SIZE))
        at = f" at {fmt_time(s['start'])}" if s["start"] >= 0 else ""
        return dict(kind="passage", id=s["id"], video_id=s["video_id"], title=f"{s['vtitle'] or 'Untitled'}{at}", source_kind=s["vkind"],
                    label=f"{KIND_LABELS.get(s['vkind'], 'Video')} passage", date=None, text=" ".join(c["text"] for c in chunk), start=s["start"],
                    link=video_link({"youtube_id": s["youtube_id"]}, s["start"]))
    if kind == "document":
        d = db.row("SELECT * FROM documents WHERE id=?", (ref_id,))
        if not d:
            return None
        res = json.loads(d["results"] or "[]")
        res_txt = "; ".join(f"{r.get('test')}: {r.get('value')} {r.get('unit') or ''}".strip()
                            + (f" (range {r['reference_range']})" if r.get("reference_range") else "")
                            + (f" [flag on report: {r['flag_as_written']}]" if r.get("flag_as_written") else "") for r in res[:20])
        return dict(kind="document", id=d["id"], title=d["title"], date=d["document_date"],
                    label=f"Medical document ({DOC_TYPES.get(d['doc_type'], 'other')})", provider=d["provider"],
                    text=(res_txt + "\n" if res_txt else "") + (d["extracted_text"] or "")[:1500],
                    file=d["file_path"], status=d["status"])
    if kind == "question":
        q = db.row("SELECT * FROM questions WHERE id=?", (ref_id,))
        if not q:
            return None
        return dict(kind="question", id=q["id"], title=q["text"], date=q["created_at"][:10], label="Saved question",
                    text=q["answer"] or "", status=q["status"])
    return None


DOC_TYPES = {"lab_result": "test result", "visit_summary": "visit summary", "imaging_report": "imaging report",
             "prescription": "prescription", "other": "other"}


def index_document(doc_id: int) -> None:
    d = db.row("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d:
        res = " ".join(f"{r.get('test')} {r.get('value')} {r.get('unit') or ''}" for r in json.loads(d["results"] or "[]"))
        db.index_record("document", doc_id, d["title"], f"{DOC_TYPES.get(d['doc_type'], '')} {d['provider'] or ''} {res} {d['extracted_text'] or ''}")


PASSAGE_SIZE = 6  # transcript segments per searchable passage
KIND_LABELS = {"youtube": "Video", "video_file": "Video", "article": "Article", "reddit": "Community thread", "image": "Photo/clipping"}


def index_note(note_id: int) -> None:
    n = db.row("SELECT * FROM notes WHERE id=?", (note_id,))
    if n:
        db.index_record("note", note_id, n["title"], f"{CATEGORY_LABELS.get(n['category'], '')} {n['current_text']} {n['ai_summary'] or ''}")


def index_symptom(sid: int) -> None:
    s = db.row("SELECT * FROM symptoms WHERE id=?", (sid,))
    if s:
        db.index_record("symptom", sid, s["symptom"], f"{s['symptom']} {s['context'] or ''} {s['details'] or ''}")


def index_question(qid: int) -> None:
    q = db.row("SELECT * FROM questions WHERE id=?", (qid,))
    if q:
        db.index_record("question", qid, q["text"], f"{q['text']} {q['answer'] or ''}")


def index_moment(mid: int) -> None:
    m = db.row("SELECT * FROM moments WHERE id=?", (mid,))
    if m:
        db.index_record("moment", mid, m["heading"],
                        f"{m['explanation']} {' '.join(json.loads(m['claims']))} {' '.join(json.loads(m['topics']))} {m['excerpt']}")


def index_video_passages(video_id: int) -> None:
    segs = db.rows("SELECT id, idx, text FROM segments WHERE video_id=? ORDER BY idx", (video_id,))
    with db.tx() as c:
        c.execute("DELETE FROM record_fts WHERE kind='passage' AND ref_id IN (SELECT id FROM segments WHERE video_id=?)", (video_id,))
        for i in range(0, len(segs), PASSAGE_SIZE):
            chunk = segs[i:i + PASSAGE_SIZE]
            c.execute("INSERT INTO record_fts(kind, ref_id, title, body) VALUES('passage',?,?,?)",
                      (chunk[0]["id"], "", " ".join(s["text"] for s in chunk)))


def reindex_all() -> None:
    with db.tx() as c:
        c.execute("DELETE FROM record_fts")
    for n in db.rows("SELECT id FROM notes"):
        index_note(n["id"])
    for s in db.rows("SELECT id FROM symptoms"):
        index_symptom(s["id"])
    for q in db.rows("SELECT id FROM questions"):
        index_question(q["id"])
    for m in db.rows("SELECT id FROM moments"):
        index_moment(m["id"])
    for v in db.rows("SELECT id FROM videos"):
        index_video_passages(v["id"])
    for d in db.rows("SELECT id FROM documents"):
        index_document(d["id"])
