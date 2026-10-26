"""SQLite storage. One file, one user. Full-text search (FTS5) indexes every personal record,
transcript segment, and reference passage so retrieval works without any AI call."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH, REFERENCES_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY,
  youtube_id TEXT, url TEXT, title TEXT, channel TEXT,
  transcript_source TEXT,            -- youtube_captions | pasted | uploaded_file | none
  transcript_note TEXT,              -- e.g. "auto-generated English captions", "pasted by user"
  transcript_hash TEXT,
  status TEXT NOT NULL DEFAULT 'new',-- new | needs_transcript | transcript_ready | analyzed | error
  status_detail TEXT,
  media_path TEXT,                   -- user-uploaded video file (only source of frames)
  media_note TEXT,
  summary TEXT, analysis_version TEXT, injection_flags TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, start REAL NOT NULL, duration REAL NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS moments (
  id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, heading TEXT NOT NULL, explanation TEXT NOT NULL,
  kind TEXT NOT NULL, claims TEXT NOT NULL, topics TEXT NOT NULL,
  seg_start INTEGER NOT NULL, seg_end INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
  excerpt TEXT NOT NULL,
  frame_status TEXT NOT NULL DEFAULT 'unavailable', -- captured | unavailable
  frame_path TEXT, frame_time REAL, frame_note TEXT,
  saved INTEGER NOT NULL DEFAULT 0, analysis_version TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  category TEXT NOT NULL,            -- symptom_observation | video_or_article | diet_lifestyle | doctor_instruction | personal_question
  title TEXT NOT NULL, original_text TEXT NOT NULL, current_text TEXT NOT NULL,
  ai_summary TEXT, source TEXT NOT NULL, -- typed | pasted | text_upload | markdown_upload | image
  source_detail TEXT, image_path TEXT, recorded_on TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS note_revisions (
  id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  text TEXT NOT NULL, edited_at TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS symptoms (
  id INTEGER PRIMARY KEY, symptom TEXT NOT NULL, occurred_on TEXT NOT NULL,
  severity INTEGER NOT NULL, duration TEXT, context TEXT, details TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connections (
  id INTEGER PRIMARY KEY,
  from_kind TEXT NOT NULL, from_id INTEGER NOT NULL,     -- moment | note | symptom (the NEW material)
  to_kind TEXT NOT NULL, to_id INTEGER NOT NULL,         -- note | symptom | moment (the earlier record)
  relation TEXT NOT NULL,            -- repeats | adds_detail | conflicts | related
  new_information TEXT NOT NULL, why_related TEXT NOT NULL, uncertain TEXT NOT NULL,
  clinician_question TEXT, interpretation TEXT,
  status TEXT NOT NULL DEFAULT 'active',  -- active | dismissed | corrected
  user_correction TEXT, cache_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_checks (
  id INTEGER PRIMARY KEY, moment_id INTEGER NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  claim TEXT NOT NULL, passage_id TEXT, verdict TEXT NOT NULL, -- supports | contradicts | not_established
  explanation TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL,
  origin_kind TEXT, origin_id INTEGER,      -- moment | connection | note | chat | manual
  status TEXT NOT NULL DEFAULT 'open',      -- open | asked | answered
  answer TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS medications (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, instruction_text TEXT NOT NULL,
  source TEXT NOT NULL,                     -- typed | ai_extracted_reviewed
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS med_schedules (   -- never edited in place: a change ends one row and adds another
  id INTEGER PRIMARY KEY, medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
  dose_text TEXT NOT NULL, times TEXT NOT NULL, days TEXT NOT NULL, -- times JSON ["07:00"], days "daily" or "Mon,Wed"
  starts_on TEXT NOT NULL, ends_on TEXT, change_reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dose_logs (
  id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES med_schedules(id) ON DELETE CASCADE,
  due_at TEXT NOT NULL, status TEXT NOT NULL, -- taken | skipped
  logged_at TEXT NOT NULL, UNIQUE(schedule_id, due_at)
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, clinician TEXT, location TEXT,
  starts_at TEXT, duration_min INTEGER NOT NULL DEFAULT 30,
  status TEXT NOT NULL,                    -- draft_request | requested | confirmed | completed | cancelled
  booking_link TEXT, request_text TEXT, notes TEXT,
  created_by TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (  -- anything the AI proposes waits here for a human
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, summary TEXT NOT NULL,
  proposed_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
  created_at TEXT NOT NULL, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (      -- medical documents she uploads (test results, visit summaries)
  id INTEGER PRIMARY KEY, title TEXT NOT NULL,
  doc_type TEXT NOT NULL DEFAULT 'other',   -- lab_result | visit_summary | imaging_report | prescription | other
  document_date TEXT, provider TEXT,
  file_path TEXT NOT NULL, mime TEXT NOT NULL, original_name TEXT,
  extracted_text TEXT, results TEXT,         -- results: JSON list copied as written (test, value, unit, range, flag)
  read_by TEXT,                              -- pdf_text | ai_image | ai_text | none
  status TEXT NOT NULL DEFAULT 'uploaded',   -- uploaded | reviewed
  notes TEXT, is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (         -- order REQUESTS only; UmmaCare never purchases anything
  id INTEGER PRIMARY KEY, item TEXT NOT NULL,
  kind TEXT NOT NULL,                        -- prescription_refill | supplement | other
  quantity TEXT, store_link TEXT, notes TEXT,
  status TEXT NOT NULL DEFAULT 'draft',      -- draft | placed | received | cancelled
  created_by TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_cache (key TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_log (     -- telemetry: counts only, never health text
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, workflow TEXT NOT NULL, model TEXT NOT NULL,
  requests INTEGER, input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
  reasoning_tokens INTEGER, latency_ms INTEGER, cost_usd REAL, cache_hit INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL, error TEXT, gateway_cache TEXT
);
CREATE TABLE IF NOT EXISTS safety_events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS references_ (
  id TEXT PRIMARY KEY, publisher TEXT, title TEXT, section TEXT, url TEXT, condition TEXT,
  reviewed TEXT, retrieved TEXT, text TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(kind UNINDEXED, ref_id UNINDEXED, title, body, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS reference_fts USING fts5(ref_id UNINDEXED, section, body, tokenize='porter unicode61');
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    r = rows(sql, params)
    return r[0] if r else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def get_setting(key: str, default: str | None = None) -> str | None:
    r = row("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


SOURCE_COLUMNS = {"kind": "TEXT NOT NULL DEFAULT 'youtube'",   # youtube | video_file | article | reddit | image
                  "source_url": "TEXT", "site": "TEXT", "image_path": "TEXT"}


def init() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(videos)").fetchall()}
        for col, decl in SOURCE_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE videos ADD COLUMN {col} {decl}")
        c.execute("UPDATE videos SET kind='video_file' WHERE youtube_id IS NULL AND kind='youtube'")
        if c.execute("SELECT COUNT(*) FROM references_").fetchone()[0] == 0:
            data = json.loads(REFERENCES_FILE.read_text())
            for p in data["passages"]:
                c.execute("INSERT INTO references_ VALUES(?,?,?,?,?,?,?,?,?)",
                          (p["id"], p["publisher"], p["title"], p["section"], p["url"], p["condition"],
                           p["reviewed"], p["retrieved"], p["text"]))
                c.execute("INSERT INTO reference_fts(ref_id, section, body) VALUES(?,?,?)",
                          (p["id"], p["section"], p["text"]))


# --- full-text index of personal records and video passages -----------------------------

def index_record(kind: str, ref_id: int, title: str, body: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM record_fts WHERE kind=? AND ref_id=?", (kind, ref_id))
        c.execute("INSERT INTO record_fts(kind, ref_id, title, body) VALUES(?,?,?,?)", (kind, ref_id, title, body))


def unindex_record(kind: str, ref_id: int) -> None:
    execute("DELETE FROM record_fts WHERE kind=? AND ref_id=?", (kind, ref_id))


STOP = set("""a an the and or but if then so of to in on at for with from by is are was were be been being it its this that
these those i you he she we they me my our your their what which who whom how why when where do does did have has had
can could should would will just not no yes about into over under more most some any all very also than too
video videos saved save note notes say said says tell me show find get give know like really thing things""".split())

SYNONYMS = {
    "tired": ["fatigue", "exhausted", "energy"], "fatigue": ["tired", "exhausted", "energy"],
    "exhausted": ["fatigue", "tired"], "energy": ["fatigue", "tired"],
    "dry": ["dryness"], "eyes": ["eye"], "eye": ["eyes"], "mouth": ["saliva"],
    "diet": ["food", "gluten", "eating", "nutrition"], "food": ["diet", "eating"],
    "gluten": ["diet", "wheat"], "thyroid": ["tsh", "levothyroxine", "hashimoto"],
    "brain": ["fog", "concentration", "memory"], "fog": ["brain", "concentration", "memory"],
    "joint": ["joints", "pain"], "sleep": ["insomnia", "sleeping"], "medication": ["medicine", "levothyroxine", "dose"],
    "medicine": ["medication", "levothyroxine"], "sjogren": ["sjögren", "dry"], "hashimoto": ["thyroid"],
}


def fts_query(text: str, expand: bool = True, limit_terms: int = 14) -> str:
    """Turn free text into a safe FTS5 OR-query (quoted terms, so user text can't inject FTS syntax)."""
    words = [w for w in re.findall(r"[a-zA-Zà-ÿ0-9]+", text.lower()) if len(w) > 2 and w not in STOP]
    terms: list[str] = []
    for w in words:
        for t in [w] + (SYNONYMS.get(w, []) if expand else []):
            if t not in terms:
                terms.append(t)
    terms = terms[:limit_terms]
    return " OR ".join(f'"{t}"' for t in terms)


def search_records(text: str, kinds: tuple[str, ...] = ("note", "symptom", "moment", "question"),
                   limit: int = 8, exclude: set[tuple[str, int]] | None = None) -> list[dict[str, Any]]:
    q = fts_query(text)
    if not q:
        return []
    marks = ",".join("?" for _ in kinds)
    found = rows(f"""SELECT kind, ref_id, title, snippet(record_fts, 3, '[', ']', '…', 18) AS snip, bm25(record_fts) AS score
                     FROM record_fts WHERE record_fts MATCH ? AND kind IN ({marks}) ORDER BY score LIMIT ?""",
                 [q, *kinds, limit + len(exclude or ())])
    out = [f for f in found if (f["kind"], int(f["ref_id"])) not in (exclude or set())]
    return out[:limit]


def search_references(text: str, limit: int = 3) -> list[dict[str, Any]]:
    q = fts_query(text)
    if not q:
        return []
    hits = rows("""SELECT ref_id, bm25(reference_fts) AS score FROM reference_fts WHERE reference_fts MATCH ?
                   ORDER BY score LIMIT ?""", (q, limit))
    return [row("SELECT * FROM references_ WHERE id=?", (h["ref_id"],)) for h in hits]
