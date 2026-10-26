import { useEffect, useRef, useState } from "react";
import { api, fmtDate } from "./api";
import { ChatIcon, recordHref, toast } from "./components";

const SUGGESTIONS = [
  "What have I saved about fatigue?",
  "Which videos or articles discussed dry eyes?",
  "What did people in community threads say about fatigue?",
  "Where did I get the idea to change my diet?",
  "What did my last thyroid blood test show?",
  "What should I bring up at my next appointment?",
  "Please order a refill of my levothyroxine.",
];

type Turn = { q: string; a?: any; err?: string };

// The assistant lives on every page. Conversation persists while she moves around the app.
export function AskPanel({ open, setOpen, onChange }: { open: boolean; setOpen: (o: boolean) => void; onChange: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (open) input.current?.focus();
    const k = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open]);
  useEffect(() => {
    body.current?.scrollTo(0, body.current.scrollHeight);
  }, [turns]);

  const ask = async (text: string) => {
    if (!text.trim() || busy) return;
    setQ("");
    setBusy(true);
    const history = turns.filter((t) => t.a).slice(-3).map((t) => ({ q: t.q, a: t.a.answer }));
    setTurns((t) => [...t, { q: text }]);
    try {
      const a = await api.post("/api/chat", { message: text, history });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
      if (a.pending?.length) onChange();
    } catch (e: any) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, err: e.message } : x)));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return <button className="ask-fab" onClick={() => setOpen(true)} aria-label="Ask UmmaCare"><ChatIcon /><span className="label">Ask UmmaCare</span></button>;
  }
  return (
    <aside className="ask-panel" aria-label="Ask UmmaCare">
      <div className="ask-head">
        <h2>Ask UmmaCare</h2>
        <button className="btn ghost" onClick={() => setOpen(false)}>Close</button>
      </div>
      <div className="ask-body" ref={body}>
        {turns.length === 0 && (
          <>
            <p className="small muted">Ask about your notes, symptoms, discoveries and records. It can also draft an appointment request or a refill/order request — nothing is sent or bought until you approve and do it yourself.</p>
            <div className="suggest">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>
          </>
        )}
        {turns.map((t, i) => (
          <div key={i}>
            <div className="q">{t.q}</div>
            {t.err && <div className="error">{t.err}</div>}
            {!t.a && !t.err && <div className="a muted">Looking through your notebook…</div>}
            {t.a && <Answer a={t.a} onChange={onChange} />}
          </div>
        ))}
      </div>
      <div className="ask-foot">
        <textarea ref={input} className="textarea" style={{ minHeight: 64 }} value={q} maxLength={1500} placeholder="Ask a question…" aria-label="Your question"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
        <div className="row" style={{ justifyContent: "space-between", marginTop: 8 }}>
          <span className="meta">Not medical advice</span>
          <button className="btn primary" disabled={busy || !q.trim()} onClick={() => ask(q)}>{busy ? "Thinking…" : "Ask"}</button>
        </div>
      </div>
    </aside>
  );
}

const PENDING_DONE: Record<string, string> = {
  appointment_request: "Saved as a draft request in Calendar → Appointments. Not sent or confirmed.",
  order_request: "Saved as a draft order in Records → Medication. Nothing was bought — place it yourself.",
  save_question: "Question saved.",
};

function Answer({ a, onChange }: { a: any; onChange: () => void }) {
  const [pending, setPending] = useState<any[]>(a.pending || []);
  const decide = async (p: any, approve: boolean) => {
    const r = await api.post(`/api/pending/${p.id}`, { approve });
    setPending(pending.map((x) => (x.id === p.id ? { ...x, status: r.status } : x)));
    toast(approve ? PENDING_DONE[p.kind] || "Approved" : "Rejected — nothing saved");
    onChange();
  };
  return (
    <div className="a">
      <div style={{ whiteSpace: "pre-wrap" }}>{a.answer}</div>
      {a.interpretation && <p className="muted" style={{ marginTop: 8 }}><i>Tentative: {a.interpretation}</i></p>}
      <div className="cites">
        {a.personal_records.length > 0 && <div><div className="h">Your records</div>{a.personal_records.map((r: any) => (
          <div key={r.kind + r.id}>{r.date && <span className="meta">{fmtDate(r.date)} · </span>}<a href={recordHref(r)}>{r.title}</a></div>))}</div>}
        {a.video_passages.length > 0 && <div><div className="h">Discovery (videos, articles, threads)</div>{a.video_passages.map((r: any) => (
          <div key={r.kind + r.id}><a href={`#/discovery/${r.video_id}`}>{r.title}</a> <span className="meta">{r.label?.split(":")[0]}</span>{r.link && <> · <a href={r.link} target="_blank" rel="noreferrer">timestamp</a></>}</div>))}</div>}
        {a.references.length > 0 && <div><div className="h">Medical references</div>{a.references.map((r: any) => (
          <div key={r.id}><a href={r.url} target="_blank" rel="noreferrer">{r.publisher.split("(")[1]?.replace(")", "") || r.publisher}: {r.section}</a> <span className="meta">reviewed {r.reviewed}</span></div>))}</div>}
      </div>
      {pending.map((p) => (
        <div className="approve" key={p.id}>
          <div>{p.summary}</div>
          {p.status && p.status !== "pending" ? <div className="meta">{p.status}</div> : (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn primary sm" onClick={() => decide(p, true)}>Approve draft</button>
              <button className="btn sm" onClick={() => decide(p, false)}>Reject</button>
            </div>
          )}
        </div>
      ))}
      <details className="more"><summary className="meta">How this was answered</summary>
        <div className="meta">Tools: {a.tools_used.filter((t: string) => t !== "final_result").join(", ") || "none"} · {a.usage.input_tokens} in / {a.usage.output_tokens} out tokens · {(a.usage.latency_ms / 1000).toFixed(1)}s · ${a.usage.cost_usd.toFixed(5)}</div>
      </details>
    </div>
  );
}
