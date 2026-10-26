import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Dialog, toast } from "../components";

// ---------------------------------------------------------------- medicines + order requests
const ORDER_STATUS: Record<string, string> = { draft: "Draft — not ordered", placed: "Ordered by you", received: "Received", cancelled: "Cancelled" };

export default function Medication() {
  const [meds, setMeds] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [add, setAdd] = useState(false);
  const [change, setChange] = useState<any>(null);
  const [order, setOrder] = useState(false);
  const load = () => {
    api.get("/api/medications").then(setMeds);
    api.get("/api/orders").then(setOrders);
  };
  useEffect(load, []);
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="meta">Only what you entered. UmmaCare never guesses doses or times.</span>
        <button className="btn sm" onClick={() => setAdd(true)}>Add medicine</button>
      </div>
      <div>
        <ul className="list" style={{ marginTop: 12 }}>
          {meds.map((m) => {
            const cur = m.schedules.find((s: any) => !s.ends_on);
            return (
              <li key={m.id} style={{ padding: "12px 0" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <div className="item-title">{m.name.replace("[Demo] ", "")}{!m.active && <span className="meta"> · stopped</span>}</div>
                    {cur && <div className="meta">{cur.dose_text} · {cur.times.join(", ")} · {cur.days}</div>}
                  </div>
                </div>
                <details className="more">
                  <summary>Instructions and history</summary>
                  <div style={{ paddingLeft: 14 }}>
                    <p className="small muted">“{m.instruction_text}” <span className="meta">({m.source === "ai_extracted_reviewed" ? "copied by AI, checked by you" : "typed by you"})</span></p>
                    <table className="data">
                      <thead><tr><th>Dose</th><th>Times</th><th>From</th><th>To</th><th>Why</th></tr></thead>
                      <tbody>{m.schedules.map((s: any) => (
                        <tr key={s.id} style={{ color: s.ends_on ? "var(--ink-3)" : undefined }}><td>{s.dose_text}</td><td>{s.times.join(", ")}</td><td>{fmtDate(s.starts_on)}</td><td>{s.ends_on ? fmtDate(s.ends_on) : "now"}</td><td>{s.change_reason}</td></tr>))}</tbody>
                    </table>
                    {m.active ? (
                      <div className="row" style={{ marginTop: 8 }}>
                        <button className="btn sm" onClick={() => setChange(m)}>Record a change</button>
                        <a className="btn sm ghost" href={`/api/medications/${m.id}/calendar.ics`}>Reminders (.ics)</a>
                        <button className="btn sm ghost" onClick={async () => { if (confirm("Mark as stopped? History is kept.")) { await api.post(`/api/medications/${m.id}/stop`); load(); } }}>Stopped taking it</button>
                      </div>
                    ) : null}
                  </div>
                </details>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="section">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Order requests</h2>
          <button className="btn sm" onClick={() => setOrder(true)}>New request</button>
        </div>
        <p className="meta">Refills and supplements you plan to order. UmmaCare doesn't buy anything — place the order with your pharmacy or store, then update the status. Check supplements with your doctor or pharmacist first.</p>
        {orders.length === 0 && <p className="empty">No order requests.</p>}
        <ul className="list">
          {orders.map((o) => (
            <li key={o.id} className="item" style={{ cursor: "default", alignItems: "center" }}>
              <div className="grow">
                <div>{o.item.replace("[Demo] ", "")}{o.quantity ? <span className="meta"> · {o.quantity}</span> : null}</div>
                <div className="meta">{o.kind === "prescription_refill" ? "Prescription refill" : o.kind === "supplement" ? "Supplement" : "Other"} · {o.created_by.startsWith("chat_agent") ? "drafted by the assistant, approved by you" : "added by you"}{o.store_link && <> · <a href={o.store_link} target="_blank" rel="noreferrer">store link</a></>}</div>
              </div>
              <select className="select" value={o.status} aria-label={`Status of ${o.item}`} onChange={async (e) => { await api.patch(`/api/orders/${o.id}`, { status: e.target.value }); load(); }}>
                {Object.entries(ORDER_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </li>
          ))}
        </ul>
      </div>
      {add && <AddMedicine onClose={() => { setAdd(false); load(); }} />}
      {change && <ChangeSchedule med={change} onClose={() => { setChange(null); load(); }} />}
      {order && <NewOrder onClose={() => { setOrder(false); load(); }} />}
    </div>
  );
}

function NewOrder({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState<any>({ item: "", kind: "prescription_refill", quantity: "", store_link: "", notes: "" });
  const [err, setErr] = useState("");
  const save = async () => {
    try { await api.post("/api/orders", { ...f, store_link: f.store_link || null }); toast("Order request saved"); onClose(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog title="New order request" onClose={onClose} foot={<button className="btn primary" disabled={!f.item.trim()} onClick={save}>Save request</button>}>
      <div className="field"><label htmlFor="oi">Item</label><input id="oi" className="input" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} placeholder="e.g. Levothyroxine 75 mcg refill" /></div>
      <div className="split">
        <div className="field"><label htmlFor="ok">Type</label><select id="ok" className="select" style={{ width: "100%" }} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="prescription_refill">Prescription refill</option><option value="supplement">Supplement</option><option value="other">Other</option></select></div>
        <div className="field"><label htmlFor="oq">Quantity</label><input id="oq" className="input" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></div>
      </div>
      <div className="field"><label htmlFor="ol">Pharmacy or store link <span className="hint">optional</span></label><input id="ol" className="input" value={f.store_link} onChange={(e) => setF({ ...f, store_link: e.target.value })} placeholder="https://…" /></div>
      {f.kind === "supplement" && <p className="hint">Some supplements (e.g. iron, calcium) can affect thyroid medicine. Ask your doctor or pharmacist first.</p>}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

function AddMedicine({ onClose }: { onClose: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [label, setLabel] = useState("");
  const [f, setF] = useState<any>({ name: "", instruction_text: "", dose_text: "", times: "", days: "daily", starts_on: today, source: "typed" });
  const [missing, setMissing] = useState<string[]>([]);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const extract = async () => {
    setBusy(true); setErr("");
    try {
      const p = (await api.post("/api/medications/extract", { text: label })).proposal;
      setF({ ...f, name: p.name, instruction_text: label, dose_text: p.dose_text, times: p.times.join(", "), days: p.days || "", source: "ai_extracted_reviewed" });
      setMissing(p.missing.concat(p.timing_words ? [`Timing as written: “${p.timing_words}” — choose clock times yourself`] : []));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const save = async () => {
    setErr("");
    try {
      await api.post("/api/medications", { ...f, times: f.times.split(",").map((t: string) => t.trim()).filter(Boolean), reviewed });
      toast("Medicine saved"); onClose();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog title="Add medicine" onClose={onClose} foot={<button className="btn primary" onClick={save}>Save</button>}>
      <details className="more">
        <summary>Copy from a pharmacy label</summary>
        <textarea className="textarea" style={{ minHeight: 80 }} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Paste the label text" aria-label="Label text" />
        <button className="btn sm" style={{ marginTop: 8 }} disabled={busy || label.length < 5} onClick={extract}>{busy ? "Reading…" : "Copy into fields"}</button>
      </details>
      {f.source === "ai_extracted_reviewed" && <div className="notice warn" style={{ margin: "8px 0 16px" }}>Check every field. Empty fields weren't on the label.{missing.length > 0 && <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{missing.map((m, i) => <li key={i}>{m}</li>)}</ul>}</div>}
      <div className="field"><label htmlFor="mn">Name</label><input id="mn" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} /></div>
      <div className="field"><label htmlFor="mi">Instructions as written</label><textarea id="mi" className="textarea" style={{ minHeight: 60 }} value={f.instruction_text} onChange={(e) => set("instruction_text", e.target.value)} /></div>
      <div className="split">
        <div className="field"><label htmlFor="md">Dose</label><input id="md" className="input" value={f.dose_text} onChange={(e) => set("dose_text", e.target.value)} placeholder="75 mcg" /></div>
        <div className="field"><label htmlFor="mt">Times <span className="hint">24h, comma separated</span></label><input id="mt" className="input" value={f.times} onChange={(e) => set("times", e.target.value)} placeholder="07:00" /></div>
      </div>
      <div className="split">
        <div className="field"><label htmlFor="my">Days</label><input id="my" className="input" value={f.days} onChange={(e) => set("days", e.target.value)} placeholder="daily, or Mon,Wed" /></div>
        <div className="field"><label htmlFor="ms">Starting</label><input id="ms" type="date" className="input" value={f.starts_on} onChange={(e) => set("starts_on", e.target.value)} /></div>
      </div>
      {f.source === "ai_extracted_reviewed" && <label className="check"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I checked these against my label</label>}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

function ChangeSchedule({ med, onClose }: { med: any; onClose: () => void }) {
  const cur = med.schedules.find((s: any) => !s.ends_on) || med.schedules[0];
  const [f, setF] = useState({ dose_text: cur?.dose_text || "", times: cur?.times.join(", ") || "", days: cur?.days || "daily", starts_on: new Date().toISOString().slice(0, 10), reason: "" });
  const [err, setErr] = useState("");
  const save = async () => {
    try {
      await api.post(`/api/medications/${med.id}/schedule`, { ...f, times: f.times.split(",").map((t) => t.trim()).filter(Boolean) });
      toast("Change recorded. Earlier schedule kept in history."); onClose();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog title={`Change: ${med.name.replace("[Demo] ", "")}`} onClose={onClose} foot={<button className="btn primary" onClick={save}>Save change</button>}>
      <p className="small muted">Enter the change your prescriber made. Past logs stay as they were.</p>
      <div className="split">
        <div className="field"><label htmlFor="cd">New dose</label><input id="cd" className="input" value={f.dose_text} onChange={(e) => setF({ ...f, dose_text: e.target.value })} /></div>
        <div className="field"><label htmlFor="ct">Times</label><input id="ct" className="input" value={f.times} onChange={(e) => setF({ ...f, times: e.target.value })} /></div>
      </div>
      <div className="split">
        <div className="field"><label htmlFor="cy">Days</label><input id="cy" className="input" value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} /></div>
        <div className="field"><label htmlFor="cs">Starting</label><input id="cs" type="date" className="input" value={f.starts_on} onChange={(e) => setF({ ...f, starts_on: e.target.value })} /></div>
      </div>
      <div className="field"><label htmlFor="cr">Why</label><input id="cr" className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Dr. Kim changed it after my blood test" /></div>
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

