"""Medications, dose logs, appointments, calendar export. Deterministic code only — no AI here.

Rules: doses and schedules are only what the user entered or reviewed; a schedule change ends the old
row and starts a new one (history is never overwritten); 'requested' is never shown as 'confirmed'."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db

LOCAL_TZ = ZoneInfo("America/New_York")
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _applies(days: str, d: date) -> bool:
    return days.strip().lower() == "daily" or DAY_NAMES[d.weekday()] in [x.strip()[:3].title() for x in days.split(",")]


def doses_for_day(d: date) -> list[dict]:
    """Scheduled doses for a day, with taken/skipped/unrecorded status from the log."""
    ds = d.isoformat()
    scheds = db.rows("""SELECT s.*, m.name FROM med_schedules s JOIN medications m ON m.id=s.medication_id
                        WHERE m.active=1 AND s.starts_on<=? AND (s.ends_on IS NULL OR s.ends_on>=?)""", (ds, ds))
    out = []
    for s in scheds:
        if not _applies(s["days"], d):
            continue
        for t in json.loads(s["times"]):
            due = f"{ds}T{t}"
            log = db.row("SELECT status, logged_at FROM dose_logs WHERE schedule_id=? AND due_at=?", (s["id"], due))
            out.append({"schedule_id": s["id"], "medication": s["name"], "dose_text": s["dose_text"], "due_at": due,
                        "time": t, "status": log["status"] if log else "unrecorded", "logged_at": log["logged_at"] if log else None})
    return sorted(out, key=lambda x: x["due_at"])


def log_dose(schedule_id: int, due_at: str, status: str) -> None:
    if status not in ("taken", "skipped", "unrecorded"):
        raise ValueError("status must be taken, skipped, or unrecorded")
    if status == "unrecorded":
        db.execute("DELETE FROM dose_logs WHERE schedule_id=? AND due_at=?", (schedule_id, due_at))
        return
    db.execute("""INSERT INTO dose_logs(schedule_id, due_at, status, logged_at) VALUES(?,?,?,?)
                  ON CONFLICT(schedule_id, due_at) DO UPDATE SET status=excluded.status, logged_at=excluded.logged_at""",
               (schedule_id, due_at, status, db.now()))


def change_schedule(medication_id: int, dose_text: str, times: list[str], days: str, starts_on: str, reason: str) -> int:
    """End the current schedule the day before `starts_on` and add the new one. Old logs stay attached to the old row."""
    prev_day = (date.fromisoformat(starts_on) - timedelta(days=1)).isoformat()
    with db.tx() as c:
        c.execute("UPDATE med_schedules SET ends_on=? WHERE medication_id=? AND ends_on IS NULL", (prev_day, medication_id))
        cur = c.execute("""INSERT INTO med_schedules(medication_id, dose_text, times, days, starts_on, change_reason, created_at)
                           VALUES(?,?,?,?,?,?,?)""", (medication_id, dose_text, json.dumps(times), days, starts_on, reason, db.now()))
        return cur.lastrowid


def _ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_dt(local_iso: str) -> str:
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def appointment_ics(appt_ids: list[int] | None = None) -> str:
    q = "SELECT * FROM appointments WHERE starts_at IS NOT NULL AND status IN ('requested','confirmed')"
    appts = db.rows(q + (f" AND id IN ({','.join('?' for _ in appt_ids)})" if appt_ids else ""), appt_ids or [])
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UmmaCare//Care Calendar//EN", "CALSCALE:GREGORIAN"]
    for a in appts:
        start = datetime.fromisoformat(a["starts_at"])
        end = (start + timedelta(minutes=a["duration_min"])).isoformat()
        status_word = "CONFIRMED by clinic (entered by you)" if a["status"] == "confirmed" else "REQUESTED - not yet confirmed by the clinic"
        title = a["title"] if a["status"] == "confirmed" else f"[Requested, not confirmed] {a['title']}"
        desc = f"Status: {status_word}.\n" + (f"Clinician: {a['clinician']}\n" if a["clinician"] else "") + \
               (f"Booking link: {a['booking_link']}\n" if a["booking_link"] else "") + "Exported from UmmaCare. A calendar entry is not proof of booking."
        lines += ["BEGIN:VEVENT", f"UID:ummacare-appt-{a['id']}@local", f"DTSTAMP:{stamp}",
                  f"DTSTART:{_ics_dt(a['starts_at'])}", f"DTEND:{_ics_dt(end)}", f"SUMMARY:{_ics_escape(title)}",
                  f"LOCATION:{_ics_escape(a['location'] or '')}", f"DESCRIPTION:{_ics_escape(desc)}",
                  f"STATUS:{'CONFIRMED' if a['status'] == 'confirmed' else 'TENTATIVE'}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def medication_ics(medication_id: int) -> str:
    s = db.row("""SELECT s.*, m.name FROM med_schedules s JOIN medications m ON m.id=s.medication_id
                  WHERE s.medication_id=? AND s.ends_on IS NULL""", (medication_id,))
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UmmaCare//Medication Reminders//EN"]
    if s:
        byday = "" if s["days"].lower() == "daily" else ";BYDAY=" + ",".join(d.strip()[:2].upper() for d in s["days"].split(","))
        for t in json.loads(s["times"]):
            start = f"{s['starts_on']}T{t}"
            lines += ["BEGIN:VEVENT", f"UID:ummacare-med-{s['id']}-{t.replace(':', '')}@local", f"DTSTAMP:{stamp}",
                      f"DTSTART:{_ics_dt(start)}", "DURATION:PT10M", f"RRULE:FREQ=DAILY{byday}" if not byday else f"RRULE:FREQ=WEEKLY{byday}",
                      f"SUMMARY:{_ics_escape(s['name'] + ' ' + s['dose_text'])}",
                      f"DESCRIPTION:{_ics_escape('Reminder from your own UmmaCare medication entry. Follow your prescriber.')}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
