import { useEffect, useState } from "react";
import { api, fmtDateTime } from "../api";
import { toast } from "../components";

const Row = ({ title, desc, children }: any) => (
  <div className="row" style={{ justifyContent: "space-between", padding: "16px 0", borderBottom: "1px solid var(--line)", alignItems: "flex-start" }}>
    <div className="grow" style={{ minWidth: 220 }}><div>{title}</div><div className="meta">{desc}</div></div>
    <div className="row">{children}</div>
  </div>
);

export default function SettingsPage({ onStatus }: { onStatus: () => void }) {
  const [s, setS] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [confirmText, setConfirmText] = useState("");
  const load = () => {
    api.get("/api/status").then(setS);
    api.get("/api/usage").then(setUsage);
    api.get("/api/safety-events").then(setEvents);
  };
  useEffect(load, []);
  if (!s) return null;
  const consent = async (agree: boolean) => { await api.post("/api/consent", { agree }); load(); onStatus(); };
  return (
    <div className="page">
      <div className="head"><div><h1>Settings</h1><div className="sub">Your data stays on this computer.</div></div></div>
      <div style={{ borderTop: "1px solid var(--line)" }}>
        <Row title="AI features" desc={`${s.consent ? "On" : "Off"} · ${s.model} via Portkey${s.key_present ? "" : " · no API key found"}. Only the text a button needs is sent.`}>
          {s.consent ? <button className="btn" onClick={() => consent(false)}>Turn off</button> : <button className="btn primary" onClick={() => consent(true)}>Turn on</button>}
        </Row>
        <Row title="Daily AI budget" desc={`$${s.spent_today_usd.toFixed(4)} of $${s.daily_budget_usd.toFixed(2)} used today. AI pauses at the limit.`} />
        <Row title="Export" desc="Everything you've saved, as a JSON file."><a className="btn" href="/api/export">Export</a></Row>
        <Row title="Demo records" desc="Invented examples marked “demo”. Not real health data.">
          {s.demo_loaded ? <button className="btn" onClick={async () => { await api.post("/api/demo/remove"); toast("Demo records removed"); load(); }}>Remove</button>
            : <button className="btn" onClick={async () => { await api.post("/api/demo/load"); toast("Demo records loaded"); load(); }}>Load</button>}
        </Row>
        <Row title="Delete all data" desc="Notes, symptoms, videos, records, medicines, appointments and uploaded files. Type DELETE MY DATA to confirm.">
          <input className="input" style={{ width: 180 }} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} aria-label="Type DELETE MY DATA" />
          <button className="btn danger" disabled={confirmText !== "DELETE MY DATA"} onClick={async () => { await api.post("/api/delete-all", { confirm: confirmText }); toast("All data deleted"); setConfirmText(""); load(); }}>Delete</button>
        </Row>
      </div>
      <details className="more" style={{ marginTop: 24 }}>
        <summary>AI usage log <span className="meta">· counts only, never health text</span></summary>
        <table className="data">
          <thead><tr><th>When</th><th>Step</th><th>In</th><th>Cached</th><th>Out</th><th>Time</th><th>Cost</th></tr></thead>
          <tbody>{usage?.rows.slice(0, 30).map((r: any) => (
            <tr key={r.id}><td className="meta">{fmtDateTime(r.ts)}</td><td>{r.workflow}{r.cache_hit ? " (reused)" : ""}{r.ok ? "" : " — failed"}</td>
              <td>{r.input_tokens}</td><td>{r.cached_tokens}</td><td>{r.output_tokens}</td><td>{(r.latency_ms / 1000).toFixed(1)}s</td><td>${(r.cost_usd || 0).toFixed(5)}</td></tr>))}</tbody>
        </table>
      </details>
      <details className="more">
        <summary>Safety events <span className="meta">· {events.length}</span></summary>
        {events.slice(0, 20).map((e) => <div key={e.id} className="small" style={{ padding: "6px 0 6px 14px" }}>{e.kind.replace(/_/g, " ")} <span className="meta">· {e.source} · {fmtDateTime(e.ts)}</span><div className="meta">{e.detail}</div></div>)}
      </details>
    </div>
  );
}
