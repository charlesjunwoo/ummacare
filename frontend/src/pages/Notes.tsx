import { useEffect, useState } from "react";
import { api, CATEGORY_LABELS, fmtDate, fmtDateTime, go, SOURCE_LABELS } from "../api";
import { Connection, Guide, NoteDialog, recordHref, SearchBox, toast } from "../components";

const monthLabel = (iso: string) => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "long", year: "numeric" });

export function JournalPage() {
  const [notes, setNotes] = useState<any[] | null>(null);
  const [today, setToday] = useState<any>(null);
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => { api.get(`/api/notes${cat ? `?category=${cat}` : ""}`).then(setNotes); }, [cat]);
  useEffect(() => { api.get("/api/dashboard").then(setToday); }, []);
  useEffect(() => { if (!q.trim()) setResults(null); }, [q]);
  const search = async () => setResults(q.trim() ? await api.get(`/api/search?q=${encodeURIComponent(q)}`) : null);

  const pending = today?.pending?.length || 0;
  const groups: [string, any[]][] = [];
  (notes || []).forEach((n) => {
    const m = monthLabel(n.recorded_on);
    if (!groups.length || groups[groups.length - 1][0] !== m) groups.push([m, []]);
    groups[groups.length - 1][1].push(n);
  });

  return (
    <div className="page">
      <div className="head">
        <div>
          <h1>Journal</h1>
          {pending > 0 && <div className="sub"><a href="#/calendar">{pending} draft{pending > 1 ? "s" : ""} from the assistant to review</a></div>}
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}>New note</button>
      </div>

      <Guide>“New note” to write, upload or photograph a page · Search finds anything you've saved · Open a note to see related videos and records.</Guide>
      <div className="row toolbar" style={{ marginBottom: 8 }}>
        <SearchBox value={q} onChange={setQ} onEnter={search} placeholder="Search notes, symptoms, videos and records" label="Search everything" />
        <select className="select" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Filter notes">
          <option value="">All notes</option>
          {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {results ? (
        <div>
          <div className="date-head">{results.results.length} result{results.results.length === 1 ? "" : "s"} for “{q}” <button className="linkbtn meta" onClick={() => { setQ(""); setResults(null); }}>clear</button></div>
          <ul className="list">
            {results.results.map((r: any) => (
              <li key={r.kind + r.id}>
                <a className="item" href={recordHref(r)}>
                  <div className="grow">
                    <div className="item-title">{r.title}</div>
                    <div className="item-preview" dangerouslySetInnerHTML={{ __html: snippet(r.snippet) }} />
                    <div className="meta">{r.label}{r.date ? ` · ${fmtDate(r.date)}` : ""}</div>
                  </div>
                </a>
              </li>
            ))}
          </ul>
          {results.references.length > 0 && (
            <div className="section">
              <h2>From the medical reference pages</h2>
              {results.references.map((r: any) => (
                <div key={r.id} className="small" style={{ marginBottom: 6 }}><a href={r.url} target="_blank" rel="noreferrer">{r.section}</a> <span className="meta">· {r.publisher.match(/\((\w+)\)/)?.[1]} · reviewed {r.reviewed}</span></div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          {notes && notes.length === 0 && <p className="empty">No notes yet. Start with “New note”.</p>}
          {groups.map(([m, ns]) => (
            <section key={m}>
              <div className="date-head">{m}</div>
              <ul className="list">
                {ns.map((n) => (
                  <li key={n.id}>
                    <a className="item" href={`#/notes/${n.id}`}>
                      <div className="paper" aria-hidden>{n.image_path && <img src={`/media/${n.image_path}`} alt="" />}</div>
                      <div className="grow">
                        <div className="item-title">{n.title}</div>
                        <div className="item-preview">{n.ai_summary || n.current_text}</div>
                        <div className="meta">{fmtDate(n.recorded_on)} · {CATEGORY_LABELS[n.category]} · {SOURCE_LABELS[n.source] || n.source}{n.is_demo ? " · demo" : ""}</div>
                      </div>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
      {adding && <NoteDialog onClose={() => setAdding(false)} onSaved={(id) => { setAdding(false); go(`#/notes/${id}`); }} />}
    </div>
  );
}

function snippet(s: string) {
  const e = (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return e.replace(/\[/g, "<b>").replace(/\]/g, "</b>");
}

export function NoteDetail({ id }: { id: number }) {
  const [n, setN] = useState<any>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api.get(`/api/notes/${id}`).then((x) => { setN(x); setText(x.current_text); });
  useEffect(() => { load(); }, [id]);
  if (!n) return null;
  const save = async () => {
    await api.put(`/api/notes/${id}`, { text, reason: reason || "Corrected by me" });
    setEditing(false);
    toast("Saved. The original and earlier versions are kept.");
    load();
  };
  const connect = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await api.post(`/api/notes/${id}/connect`);
      setMsg(r.connections ? "" : r.message || "Nothing closely related found.");
      load();
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="page">
      <a className="back" href="#/journal">← Journal</a>
      <div className="meta">{CATEGORY_LABELS[n.category]} · {fmtDate(n.recorded_on)} · {SOURCE_LABELS[n.source] || n.source}{n.source_detail ? ` (${n.source_detail})` : ""}</div>
      <div className="head" style={{ marginTop: 4 }}>
        <h1>{n.title}</h1>
        {!editing && <button className="btn" onClick={() => setEditing(true)}>Edit</button>}
      </div>
      <Guide>Edit your note anytime (the original is kept) · Related videos and records are listed below.</Guide>
      {n.category === "doctor_instruction" && <p className="hint">What you recorded a doctor said — not verified clinical guidance.</p>}
      {editing ? (
        <>
          <textarea className="textarea" style={{ minHeight: 240 }} value={text} onChange={(e) => setText(e.target.value)} aria-label="Note text" />
          <div className="row" style={{ marginTop: 8 }}>
            <input className="input grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for the change (optional)" aria-label="Reason" />
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn primary" onClick={save}>Save</button>
          </div>
        </>
      ) : <div className="prose">{n.current_text}</div>}

      {n.image_path && <img src={`/media/${n.image_path}`} alt="Original page" style={{ marginTop: 24, width: 320, borderRadius: 6, border: "1px solid var(--line)" }} />}
      {n.ai_summary && <><div className="voice">AI summary — your words above are the record</div><p className="small muted">{n.ai_summary}</p></>}
      {n.revisions.length > 0 && (
        <details className="more">
          <summary>Original and {n.revisions.length} edit{n.revisions.length > 1 ? "s" : ""}</summary>
          <div className="small" style={{ paddingLeft: 14 }}>
            <div className="meta">Original{n.source === "image" ? " (as read from the photo)" : ""}</div>
            <p className="prose small">{n.original_text}</p>
            {n.revisions.map((r: any) => <div key={r.id}><div className="meta">{fmtDateTime(r.edited_at)} — {r.reason}</div><p className="prose small">{r.text}</p></div>)}
          </div>
        </details>
      )}

      <div className="section">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Connections</h2>
          <button className="btn sm" disabled={busy} onClick={connect}>{busy ? "Looking…" : "Find related videos and notes"}</button>
        </div>
        {msg && <p className="small muted">{msg}</p>}
        {n.connections.length === 0 && !msg && <p className="empty">None yet.</p>}
        {n.connections.map((c: any) => <Connection key={c.id} c={c} showNew={c.to_kind === "note" && c.to_id === n.id} onChange={load} />)}
      </div>
      <hr className="div" />
      <button className="btn danger sm" onClick={async () => { if (confirm("Delete this note?")) { await api.del(`/api/notes/${id}`); go("#/journal"); } }}>Delete note</button>
    </div>
  );
}
