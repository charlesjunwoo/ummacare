import { useEffect, useRef, useState } from "react";
import { api, fmtDate, fmtDateTime } from "../api";
import { Dialog } from "../components";

type Group = { key: string; title: string; items: { ref: string; label: string; meta?: string }[] };

export default function BriefPage({ embedded = false }: { embedded?: boolean }) {
  const [c, setC] = useState<any>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [appt, setAppt] = useState<number | "">("");
  const [useAi, setUseAi] = useState(false);
  const [html, setHtml] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    api.get("/api/brief/candidates").then((x) => {
      setC(x);
      const pre = new Set<string>();
      x.questions.forEach((q: any) => pre.add(`question:${q.id}`));
      x.symptoms.slice(0, 5).forEach((s: any) => pre.add(`symptom:${s.id}`));
      x.moments.forEach((m: any) => pre.add(`moment:${m.id}`));
      setSel(pre);
      const next = x.appointments.find((a: any) => a.status === "confirmed") || x.appointments[0];
      if (next) setAppt(next.id);
    });
  }, []);
  if (!c) return null;
  const groups: Group[] = [
    { key: "question", title: "Questions", items: c.questions.map((q: any) => ({ ref: `question:${q.id}`, label: q.title })) },
    { key: "symptom", title: "Symptoms, last 60 days", items: c.symptoms.map((s: any) => ({ ref: `symptom:${s.id}`, label: s.title.split(" (")[0], meta: `${fmtDate(s.date)} · ${s.title.match(/severity \d+\/10/)?.[0] || ""}` })) },
    { key: "moment", title: "Saved video claims", items: c.moments.map((m: any) => ({ ref: `moment:${m.id}`, label: m.title, meta: m.label })) },
    { key: "document", title: "Test results and records", items: (c.documents || []).map((d: any) => ({ ref: `document:${d.id}`, label: d.title.replace("[Demo] ", ""), meta: fmtDate(d.date) })) },
    { key: "note", title: "Notes", items: c.notes.map((n: any) => ({ ref: `note:${n.id}`, label: n.title, meta: `${n.label} · ${fmtDate(n.date)}` })) },
  ];
  const toggle = (ref: string) => { const s = new Set(sel); s.has(ref) ? s.delete(ref) : s.add(ref); setSel(s); };
  const make = async () => {
    setBusy(true); setErr("");
    try { setHtml((await api.post("/api/brief", { refs: Array.from(sel), appointment_id: appt || null, use_ai: useAi })).html); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    a.download = `appointment-brief-${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
  };
  return (
    <div className={embedded ? "" : "page"}>
      {embedded ? <p className="meta" style={{ marginTop: -8 }}>Choose what to bring. You'll get one printable page.</p> : (
        <div className="head">
          <div><h1>Appointment brief</h1><div className="sub">Choose what to bring. You'll get one printable page.</div></div>
        </div>
      )}
      <div className="field">
        <label htmlFor="ap">For</label>
        <select id="ap" className="select" style={{ width: "100%" }} value={appt} onChange={(e) => setAppt(e.target.value ? +e.target.value : "")}>
          <option value="">No specific appointment</option>
          {c.appointments.map((a: any) => <option key={a.id} value={a.id}>{a.title.replace("[Demo] ", "")} — {fmtDateTime(a.starts_at)}</option>)}
        </select>
      </div>
      {c.conflicts.length > 0 && <p className="meta">{c.conflicts.length} video claim{c.conflicts.length > 1 ? "s" : ""} disagree with your records — worth including.</p>}
      <div style={{ borderTop: "1px solid var(--line)" }}>
        {groups.filter((g) => g.items.length).map((g) => {
          const n = g.items.filter((i) => sel.has(i.ref)).length;
          return (
            <details key={g.key} className="more" style={{ borderBottom: "1px solid var(--line)", padding: "4px 0" }} open={g.key === "question"}>
              <summary><span style={{ color: "var(--ink)" }}>{g.title}</span> <span className="meta">· {n} of {g.items.length}</span></summary>
              <div style={{ padding: "4px 0 10px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                {g.items.map((i) => (
                  <label key={i.ref} className="check"><input type="checkbox" checked={sel.has(i.ref)} onChange={() => toggle(i.ref)} />
                    <span>{i.label}{i.meta && <span className="meta"> · {i.meta}</span>}</span></label>
                ))}
              </div>
            </details>
          );
        })}
      </div>
      <div className="row" style={{ justifyContent: "space-between", marginTop: 20 }}>
        <label className="check"><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />Add suggested talking points</label>
        <button className="btn primary" disabled={busy || sel.size === 0} onClick={make}>{busy ? "Preparing…" : `Create brief (${sel.size})`}</button>
      </div>
      {err && <div className="error">{err}</div>}
      {html && (
        <Dialog title="Your brief" wide onClose={() => setHtml("")}
          foot={<><button className="btn" onClick={download}>Download</button><button className="btn primary" onClick={() => frame.current?.contentWindow?.print()}>Print</button></>}>
          <iframe ref={frame} title="Brief preview" srcDoc={html} style={{ width: "100%", height: "60vh", border: "1px solid var(--line)", borderRadius: 6, background: "#fff" }} />
        </Dialog>
      )}
    </div>
  );
}
