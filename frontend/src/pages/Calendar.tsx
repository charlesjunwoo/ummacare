import { useEffect, useMemo, useState } from "react";
import { api, CATEGORY_LABELS, fmtDate, fmtDateTime, go } from "../api";
import { Dialog, Sev, SymptomDialog, toast } from "../components";
import BriefPage from "./Brief";

const TABS = [["month", "Month"], ["symptoms", "Symptoms"], ["appointments", "Appointments"], ["brief", "Appointment brief"]];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Home page. Assistant drafts and today's appointments sit on top; the views below are tabs.
export default function CalendarPage({ tab = "month", tick }: { tab?: string; tick: number }) {
  const [logging, setLogging] = useState(false);
  const [v, setV] = useState(0);
  const reload = () => setV((x) => x + 1);
  const t = TABS.some(([k]) => k === tab) ? tab : "month";
  return (
    <div className="page">
      <h1 className="sr-only">Calendar</h1>
      <Pending key={`p${tick}${v}`} onChange={reload} />
      <Today key={`t${tick}${v}`} />
      <div className="row" style={{ alignItems: "flex-end", marginBottom: 24 }}>
        <nav className="seg grow" style={{ marginBottom: 0 }} aria-label="Calendar views">
          {TABS.map(([k, l]) => <a key={k} href={`#/calendar/${k}`} className={t === k ? "on" : ""} aria-current={t === k ? "page" : undefined}>{l}</a>)}
        </nav>
        {t !== "brief" && <button className="btn primary" onClick={() => setLogging(true)}>Log symptom</button>}
      </div>
      {t === "month" && <Month key={`c${tick}${v}`} />}
      {t === "symptoms" && <Symptoms key={`s${v}`} />}
      {t === "appointments" && <Appointments key={`a${tick}${v}`} />}
      {t === "brief" && <BriefPage embedded />}
      {logging && <SymptomDialog onClose={() => setLogging(false)} onSaved={reload} />}
    </div>
  );
}

// ---------------------------------------------------------------- notifications: drafts from the assistant
function Pending({ onChange }: { onChange: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { api.get("/api/pending").then((p) => setItems(p.filter((x: any) => x.status === "pending"))); }, []);
  if (!items.length) return null;
  const decide = async (p: any, approve: boolean) => {
    await api.post(`/api/pending/${p.id}`, { approve });
    toast(approve ? "Approved — saved as a draft" : "Rejected — nothing saved");
    onChange();
  };
  return (
    <div className="notice warn" style={{ marginBottom: 20 }}>
      <div style={{ fontWeight: 500, marginBottom: 6 }}>Drafted by the assistant — waiting for you</div>
      {items.map((p) => {
        const pl = JSON.parse(p.payload);
        return (
          <div key={p.id} className="row" style={{ justifyContent: "space-between", padding: "6px 0" }}>
            <span>{p.summary}{pl.reason ? ` — ${pl.reason}` : ""}{pl.quantity ? ` (${pl.quantity})` : ""}</span>
            <span className="row"><button className="btn sm primary" onClick={() => decide(p, true)}>Approve</button><button className="btn sm" onClick={() => decide(p, false)}>Reject</button></span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- today's appointments (only if there are any)
function Today() {
  const [appts, setAppts] = useState<any[]>([]);
  const today = iso(new Date());
  useEffect(() => { api.get(`/api/log/day?day=${today}`).then((d) => setAppts(d.appointments.filter((a: any) => a.status !== "cancelled"))); }, []);
  if (!appts.length) return null;
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="voice" style={{ marginTop: 0 }}>Today</div>
      {appts.map((a) => (
        <div key={a.id} className="dose">
          <span className="time">{a.starts_at?.slice(11, 16)}</span>
          <span className="grow"><b style={{ fontWeight: 500 }}>{a.title.replace("[Demo] ", "")}</b>{a.clinician ? ` · ${a.clinician}` : ""}{a.location ? ` · ${a.location}` : ""}</span>
          <span className={`tag ${a.status === "confirmed" ? "green" : "warn"}`}>{APPT_STATUS[a.status]}</span>
          <button className="btn sm" onClick={() => go("#/calendar/brief")}>Brief</button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- month
function Month() {
  const now = new Date();
  const [month, setMonth] = useState(new Date(now.getFullYear(), now.getMonth(), 1));
  const [marks, setMarks] = useState<Record<string, any>>({});
  const [sel, setSel] = useState(iso(now));
  const key = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
  useEffect(() => { api.get(`/api/log/month?month=${key}`).then(setMarks); }, [key]);
  const weeks = useMemo(() => {
    const start = new Date(month);
    start.setDate(1 - ((month.getDay() + 6) % 7));   // weeks start Monday
    const out: Date[][] = [];
    for (let w = 0; w < 6; w++) {
      out.push(Array.from({ length: 7 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + w * 7 + i); return d; }));
      if (out[w][6].getMonth() !== month.getMonth() && w >= 4) break;
    }
    return out;
  }, [month]);
  const shift = (n: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + n, 1));
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h2 className="serif" style={{ fontWeight: 500, fontSize: 22 }}>{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h2>
        <div className="row">
          <button className="btn ghost" onClick={() => shift(-1)} aria-label="Previous month">‹</button>
          <button className="btn ghost sm" onClick={() => { setMonth(new Date(now.getFullYear(), now.getMonth(), 1)); setSel(iso(now)); }}>Today</button>
          <button className="btn ghost" onClick={() => shift(1)} aria-label="Next month">›</button>
        </div>
      </div>
      <table className="cal">
        <thead><tr>{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <th key={d}>{d}</th>)}</tr></thead>
        <tbody>
          {weeks.map((w, i) => (
            <tr key={i}>{w.map((d) => {
              const k = iso(d), m = marks[k];
              const cls = [d.getMonth() !== month.getMonth() && "out", k === iso(now) && "today", k === sel && "sel"].filter(Boolean).join(" ");
              return (
                <td key={k}>
                  <button className={cls} onClick={() => setSel(k)} aria-label={d.toDateString()} aria-pressed={k === sel}>
                    <span className="num">{d.getDate()}</span>
                    {m && (
                      <div className="marks" aria-hidden>
                        {m.appointments > 0 && <span className="mk appt" />}
                        {m.doctor_notes > 0 && <span className="mk doc" />}
                        {m.symptoms > 0 && <span className="mk sym" />}
                      </div>
                    )}
                  </button>
                </td>
              );
            })}</tr>
          ))}
        </tbody>
      </table>
      <div className="legend">
        <span><i className="mk appt" /> Appointment</span><span><i className="mk doc" /> Doctor's note</span><span><i className="mk sym" /> Symptom</span>
      </div>
      <Day day={sel} />
    </div>
  );
}

function Day({ day }: { day: string }) {
  const [d, setD] = useState<any>(null);
  useEffect(() => { api.get(`/api/log/day?day=${day}`).then(setD); }, [day]);
  if (!d) return null;
  const doctor = d.notes.filter((n: any) => n.category === "doctor_instruction");
  const other = d.notes.filter((n: any) => n.category !== "doctor_instruction");
  const nothing = !d.appointments.length && !d.symptoms.length && !d.notes.length && !d.documents.length;
  return (
    <section className="section">
      <h2 className="serif" style={{ fontWeight: 500, fontSize: 20 }}>{new Date(day + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</h2>
      {nothing && <p className="empty">Nothing recorded this day.</p>}
      {d.appointments.length > 0 && <Block title="Appointments">{d.appointments.map((a: any) => (
        <div key={a.id} className="dose"><span className="time">{a.starts_at?.slice(11, 16)}</span><span className="grow">{a.title.replace("[Demo] ", "")} · {a.clinician}</span><span className="meta">{APPT_STATUS[a.status]}</span></div>))}</Block>}
      {doctor.length > 0 && <Block title="Doctor's notes">{doctor.map((n: any) => <NoteLine key={n.id} n={n} />)}</Block>}
      {d.symptoms.length > 0 && <Block title="Symptoms">{d.symptoms.map((s: any) => (
        <div key={s.id} className="dose"><span className="grow" style={{ textTransform: "capitalize" }}>{s.symptom}</span><Sev n={s.severity} /><span className="meta">{[s.duration, s.context].filter(Boolean).join(" · ")}</span></div>))}</Block>}
      {other.length > 0 && <Block title="Notes, diet and activity">{other.map((n: any) => <NoteLine key={n.id} n={n} />)}</Block>}
      {d.documents.length > 0 && <Block title="Records">{d.documents.map((x: any) => <div key={x.id} className="dose"><a href={`#/records/${x.id}`}>{x.title}</a></div>)}</Block>}
    </section>
  );
}

const Block = ({ title, children }: { title: string; children: any }) => (
  <div style={{ marginTop: 20 }}><div className="voice">{title}</div>{children}</div>
);
const NoteLine = ({ n }: { n: any }) => (
  <div className="dose"><a className="grow" href={`#/notes/${n.id}`} style={{ textDecoration: "none" }}><div>{n.title}</div><div className="item-preview">{n.current_text}</div></a><span className="meta">{CATEGORY_LABELS[n.category]}</span></div>
);

// ---------------------------------------------------------------- symptoms (chronological)
function Symptoms() {
  const [list, setList] = useState<any[] | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const load = () => api.get("/api/symptoms").then(setList);
  useEffect(() => { load(); }, []);
  const names = Array.from(new Set((list || []).map((s) => s.symptom)));
  const shown = (list || []).filter((s) => !filter || s.symptom === filter);
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <span className="meta">Your journal records how you felt. It can't show whether a condition or treatment is changing.</span>
        <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter symptoms">
          <option value="">All symptoms</option>{names.map((n) => <option key={n}>{n}</option>)}
        </select>
      </div>
      {shown.length === 0 && <p className="empty">No entries yet.</p>}
      <ul className="list">
        {shown.map((s) => (
          <li key={s.id} className="item" style={{ cursor: "default", alignItems: "center" }}>
            <span className="meta" style={{ width: 90 }}>{fmtDate(s.occurred_on)}</span>
            <div className="grow">
              <div style={{ textTransform: "capitalize" }}>{s.symptom}</div>
              <div className="meta">{[s.duration && `lasted ${s.duration}`, s.context, s.details].filter(Boolean).join(" · ")}{s.is_demo ? " · demo" : ""}</div>
            </div>
            <Sev n={s.severity} />
            <button className="btn ghost sm" disabled={busy === s.id} onClick={async () => {
              setBusy(s.id);
              try { const r = await api.post(`/api/symptoms/${s.id}/connect`); toast(r.connections ? `${r.connections} related record(s) found` : r.message || "Nothing closely related"); }
              catch (e: any) { toast(e.message); } finally { setBusy(null); }
            }}>{busy === s.id ? "Looking…" : "Related"}</button>
            <button className="btn ghost sm" aria-label="Delete entry" onClick={async () => { if (confirm("Delete this entry?")) { await api.del(`/api/symptoms/${s.id}`); load(); } }}>Delete</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- appointments
const APPT_STATUS: Record<string, string> = { draft_request: "Draft — not sent", requested: "Requested — not confirmed", confirmed: "Confirmed by clinic", completed: "Completed", cancelled: "Cancelled" };

function Appointments() {
  const [appts, setAppts] = useState<any[]>([]);
  const [add, setAdd] = useState(false);
  const [draft, setDraft] = useState<any>(null);
  const load = () => api.get("/api/appointments").then(setAppts);
  useEffect(() => { load(); }, []);
  const setStatus = async (a: any, status: string) => { await api.patch(`/api/appointments/${a.id}`, { status }); load(); };
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="meta">Mark “confirmed” only after the clinic confirms. A calendar entry isn't proof of a booking.</span>
        <span className="row"><a className="btn sm ghost" href="/api/appointments.ics">Download .ics</a><button className="btn sm" onClick={() => setAdd(true)}>Add</button></span>
      </div>
      <ul className="list" style={{ marginTop: 12 }}>
        {appts.map((a) => (
          <li key={a.id} style={{ padding: "12px 0" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <div className="item-title">{a.title.replace("[Demo] ", "")}</div>
                <div className="meta">{fmtDateTime(a.starts_at)}{a.clinician ? ` · ${a.clinician}` : ""}{a.location ? ` · ${a.location}` : ""}</div>
              </div>
              <span className={`tag ${a.status === "confirmed" ? "green" : a.status === "requested" || a.status === "draft_request" ? "warn" : ""}`}>{APPT_STATUS[a.status]}</span>
            </div>
            <div className="row" style={{ marginTop: 6 }}>
              {a.status === "draft_request" && <button className="btn sm" onClick={() => setStatus(a, "requested")}>I sent the request</button>}
              {a.status === "requested" && <button className="btn sm" onClick={() => setStatus(a, "confirmed")}>Clinic confirmed</button>}
              {a.status === "confirmed" && <button className="btn sm ghost" onClick={() => setStatus(a, "completed")}>Mark completed</button>}
              {(a.status === "draft_request" || a.status === "requested") && <button className="btn sm ghost" onClick={async () => setDraft(await api.get(`/api/appointments/${a.id}/request-draft`))}>Request message</button>}
              {a.booking_link && <a className="btn sm ghost" href={a.booking_link} target="_blank" rel="noreferrer">Booking link</a>}
              {a.status !== "cancelled" && a.status !== "completed" && <button className="btn sm ghost" onClick={() => setStatus(a, "cancelled")}>Cancel</button>}
              {a.status === "confirmed" && <button className="btn sm ghost" onClick={() => go("#/calendar/brief")}>Prepare brief</button>}
            </div>
          </li>
        ))}
      </ul>
      {add && <AddAppointment onClose={() => { setAdd(false); load(); }} />}
      {draft && (
        <Dialog title="Request message" onClose={() => setDraft(null)} foot={<>{draft.booking_link && <a className="btn" href={draft.booking_link} target="_blank" rel="noreferrer">Open booking link</a>}<button className="btn primary" onClick={() => { navigator.clipboard.writeText(draft.text); toast("Copied"); }}>Copy</button></>}>
          <p className="meta">Send this through the clinic's portal, email or phone. UmmaCare doesn't send it.</p>
          <textarea className="textarea" readOnly value={draft.text} aria-label="Request message" />
        </Dialog>
      )}
    </div>
  );
}

function AddAppointment({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState<any>({ title: "", clinician: "", location: "", starts_at: "", duration_min: 30, status: "requested", booking_link: "", notes: "" });
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const save = async () => {
    try { await api.post("/api/appointments", { ...f, starts_at: f.starts_at || null, booking_link: f.booking_link || null }); onClose(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog title="Add appointment" onClose={onClose} foot={<button className="btn primary" disabled={!f.title.trim()} onClick={save}>Save</button>}>
      <div className="field"><label htmlFor="at">What</label><input id="at" className="input" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Eye doctor check-up" /></div>
      <div className="split">
        <div className="field"><label htmlFor="ac">With</label><input id="ac" className="input" value={f.clinician} onChange={(e) => set("clinician", e.target.value)} /></div>
        <div className="field"><label htmlFor="aw">When</label><input id="aw" type="datetime-local" className="input" value={f.starts_at} onChange={(e) => set("starts_at", e.target.value)} /></div>
      </div>
      <div className="field"><label htmlFor="as">Status</label>
        <select id="as" className="select" style={{ width: "100%" }} value={f.status} onChange={(e) => set("status", e.target.value)}>
          <option value="draft_request">Draft — not sent yet</option><option value="requested">Requested — waiting for the clinic</option><option value="confirmed">Confirmed by the clinic</option>
        </select>
      </div>
      <details className="more"><summary>Location and booking link</summary>
        <div className="field"><label htmlFor="al">Where</label><input id="al" className="input" value={f.location} onChange={(e) => set("location", e.target.value)} /></div>
        <div className="field"><label htmlFor="ab">Booking link</label><input id="ab" className="input" value={f.booking_link} onChange={(e) => set("booking_link", e.target.value)} placeholder="https://…" /></div>
      </details>
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}
