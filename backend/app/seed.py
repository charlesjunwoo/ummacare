"""Load or remove the clearly labeled synthetic demo records (data/fixtures/demo_records.json)."""

from __future__ import annotations

import json
from datetime import date, timedelta

from . import db, records
import shutil

from .config import FIXTURES_DIR, MEDIA_DIR


def load_demo() -> dict:
    if db.row("SELECT 1 AS x FROM notes WHERE is_demo=1 LIMIT 1"):
        return {"loaded": False, "reason": "Demo records are already loaded."}
    data = json.loads((FIXTURES_DIR / "demo_records.json").read_text())
    ts = db.now()
    for n in data["notes"]:
        nid = db.execute("""INSERT INTO notes(category,title,original_text,current_text,source,source_detail,recorded_on,is_demo,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,1,?,?)""",
                         (n["category"], n["title"], n["text"], n["text"], n["source"], "DEMO · " + n["source_detail"], n["recorded_on"],
                          n["recorded_on"] + "T12:00:00+00:00", ts))
        records.index_note(nid)
    for s in data["symptoms"]:
        sid = db.execute("""INSERT INTO symptoms(symptom,occurred_on,severity,duration,context,details,is_demo,created_at)
                            VALUES(?,?,?,?,?,?,1,?)""", (s["symptom"], s["occurred_on"], s["severity"], s["duration"], s["context"], s["details"], ts))
        records.index_symptom(sid)
    for q in data["questions"]:
        qid = db.execute("INSERT INTO questions(text,origin_kind,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                         (q["text"], "demo", "open", q["created_at"], ts))
        records.index_question(qid)
    for m in data["medications"]:
        mid = db.execute("INSERT INTO medications(name,instruction_text,source,created_at) VALUES(?,?,?,?)",
                         ("[Demo] " + m["name"], m["instruction_text"], "typed", ts))
        for s in m["schedules"]:
            sch = db.execute("""INSERT INTO med_schedules(medication_id,dose_text,times,days,starts_on,ends_on,change_reason,created_at)
                                VALUES(?,?,?,?,?,?,?,?)""", (mid, s["dose_text"], json.dumps(s["times"]), s["days"], s["starts_on"],
                                                             s["ends_on"], s["change_reason"], ts))
            if s["ends_on"] is None:   # a week of example dose logs, with a skip and some gaps left unrecorded
                for back in range(1, 8):
                    d = (date.today() - timedelta(days=back)).isoformat()
                    for i, t in enumerate(s["times"]):
                        if (back + i) % 5 == 0:
                            continue
                        status = "skipped" if (back == 3 and i == 0) else "taken"
                        db.execute("INSERT OR IGNORE INTO dose_logs(schedule_id,due_at,status,logged_at) VALUES(?,?,?,?)",
                                   (sch, f"{d}T{t}", status, ts))
    for a in data["appointments"]:
        db.execute("""INSERT INTO appointments(title,clinician,location,starts_at,duration_min,status,booking_link,request_text,notes,created_by,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   ("[Demo] " + a["title"], a["clinician"], a["location"], a["starts_at"], a["duration_min"], a["status"],
                    a.get("booking_link"), a.get("request_text"), a.get("notes"), "demo", ts, ts))
    # a reviewed demo lab report (synthetic PDF), values copied exactly as printed
    (MEDIA_DIR / "documents").mkdir(exist_ok=True)
    shutil.copy(FIXTURES_DIR / "demo_lab_report.pdf", MEDIA_DIR / "documents" / "demo_lab_report.pdf")
    results = [{"test": "TSH", "value": "3.9", "unit": "mIU/L", "reference_range": "0.45-4.50", "flag_as_written": ""},
               {"test": "Free T4", "value": "1.1", "unit": "ng/dL", "reference_range": "0.82-1.77", "flag_as_written": ""},
               {"test": "Thyroid Peroxidase (TPO) Ab", "value": "210", "unit": "IU/mL", "reference_range": "0-34", "flag_as_written": "High"},
               {"test": "Ferritin", "value": "22", "unit": "ng/mL", "reference_range": "15-150", "flag_as_written": ""},
               {"test": "Vitamin D, 25-Hydroxy", "value": "24", "unit": "ng/mL", "reference_range": "30-100", "flag_as_written": "Low"}]
    did = db.execute("""INSERT INTO documents(title,doc_type,document_date,provider,file_path,mime,original_name,extracted_text,results,
                        read_by,status,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                     ("[Demo] Thyroid panel and labs", "lab_result", "2026-10-02", "Example Diagnostics Laboratory (ordered by Dr. Kim)",
                      "documents/demo_lab_report.pdf", "application/pdf", "demo_lab_report.pdf",
                      "SYNTHETIC DEMO FIXTURE. Results reviewed by ordering provider. Please discuss with your clinician.",
                      json.dumps(results), "none", "reviewed", ts, ts))
    records.index_document(did)
    db.execute("""INSERT INTO orders(item,kind,quantity,store_link,notes,status,created_by,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""", ("[Demo] Preservative-free artificial tears", "other", "2 boxes", None,
                                                 "Running low", "placed", "demo", ts, ts))
    return {"loaded": True}


def remove_demo() -> dict:
    with db.tx() as c:
        for kind, table in (("note", "notes"), ("symptom", "symptoms")):
            ids = [r["id"] for r in c.execute(f"SELECT id FROM {table} WHERE is_demo=1").fetchall()]
            for i in ids:
                c.execute("DELETE FROM connections WHERE (from_kind=? AND from_id=?) OR (to_kind=? AND to_id=?)", (kind, i, kind, i))
                c.execute("DELETE FROM record_fts WHERE kind=? AND ref_id=?", (kind, i))
            c.execute(f"DELETE FROM {table} WHERE is_demo=1")
        qids = [r["id"] for r in c.execute("SELECT id FROM questions WHERE origin_kind='demo'").fetchall()]
        for i in qids:
            c.execute("DELETE FROM record_fts WHERE kind='question' AND ref_id=?", (i,))
        c.execute("DELETE FROM questions WHERE origin_kind='demo'")
        c.execute("DELETE FROM medications WHERE name LIKE '[Demo] %'")
        c.execute("DELETE FROM appointments WHERE created_by='demo'")
        for r in c.execute("SELECT id FROM documents WHERE is_demo=1").fetchall():
            c.execute("DELETE FROM record_fts WHERE kind='document' AND ref_id=?", (r["id"],))
        c.execute("DELETE FROM documents WHERE is_demo=1")
        c.execute("DELETE FROM orders WHERE created_by='demo'")
    return {"removed": True}
