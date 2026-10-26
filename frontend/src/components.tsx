import { ReactNode, useEffect, useRef, useState } from "react";
import { api, CATEGORY_LABELS, fmtDate, RELATION_LABELS } from "./api";

// ---------------------------------------------------------------- toast
let toastSetter: ((m: string | null) => void) | null = null;
export const toast = (m: string) => {
  toastSetter?.(m);
  setTimeout(() => toastSetter?.(null), 3200);
};
export function ToastHost() {
  const [m, setM] = useState<string | null>(null);
  toastSetter = setM;
  return m ? <div className="toast" role="status">{m}</div> : null;
}

// ---------------------------------------------------------------- dialog
export function Dialog({ title, onClose, children, wide, foot }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; foot?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button.primary")?.focus();
    return () => window.removeEventListener("keydown", k);
  }, []);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="btn ghost" onClick={onClose} aria-label="Close">Close</button>
        </div>
        {children}
        {foot && <div className="dialog-foot">{foot}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- icons (minimal, only where they help)
export const SearchIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden><circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" /></svg>
);
export const ChatIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" strokeLinejoin="round" /></svg>
);

export function SearchBox({ value, onChange, onEnter, placeholder, label }: { value: string; onChange: (v: string) => void; onEnter?: () => void; placeholder: string; label: string }) {
  return (
    <div className="search grow">
      <SearchIcon />
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()} />
    </div>
  );
}

// ---------------------------------------------------------------- consent
export function ConsentDialog({ onDone }: { onDone: (agreed: boolean) => void }) {
  const decide = async (agree: boolean) => {
    await api.post("/api/consent", { agree });
    onDone(agree);
  };
  return (
    <Dialog title="Before using AI" onClose={() => onDone(false)}
      foot={<><button className="btn" onClick={() => decide(false)}>Not now</button><button className="btn primary" onClick={() => decide(true)}>Turn on AI</button></>}>
      <p className="small">Some features send text to OpenAI's gpt-6-luna (through Portkey): a video's transcript, short excerpts of related notes for connections and questions, and any photo or document you ask it to read.</p>
      <p className="small muted">Nothing is sent until you press a button that needs it. Your notebook, search, and appointment brief work without AI. You can turn this off in Settings.</p>
    </Dialog>
  );
}

// ---------------------------------------------------------------- processing steps
export type Step = { label: string; state: "todo" | "run" | "done" | "fail" | "warn"; detail?: string };
const ICON = { todo: "○", run: "●", done: "✓", fail: "!", warn: "–" };
export function Steps({ steps }: { steps: Step[] }) {
  return (
    <ul className="steps" aria-live="polite">
      {steps.map((s, i) => (
        <li key={i} className={s.state}>
          <span className="ic" aria-hidden>{ICON[s.state]}</span>
          <span>{s.label}{s.detail && <span className="meta"> — {s.detail}</span>}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- record references
export function recordHref(r: any): string | undefined {
  if (!r) return;
  return r.kind === "note" ? `#/notes/${r.id}` : r.kind === "symptom" ? "#/calendar/symptoms" : r.kind === "moment" || r.kind === "passage" ? `#/discovery/${r.video_id}`
    : r.kind === "document" ? `#/records/${r.id}` : r.kind === "question" ? "#/calendar/brief" : undefined;
}

export function RecordRef({ r }: { r: any }) {
  if (!r) return null;
  const href = recordHref(r);
  return (
    <span className="ref">
      {href ? <a href={href}>{r.title}</a> : r.title}
      <span className="meta"> · {r.label}{r.date ? ` · ${fmtDate(r.date)}` : ""}</span>
      {r.link && <> · <a href={r.link} target="_blank" rel="noreferrer" className="meta">open at timestamp</a></>}
    </span>
  );
}

// ---------------------------------------------------------------- connection
export function Connection({ c, onChange, showNew = false }: { c: any; onChange?: () => void; showNew?: boolean }) {
  const [edit, setEdit] = useState(false);
  const [rel, setRel] = useState(c.relation);
  const [note, setNote] = useState(c.user_correction || "");
  const act = async (action: string) => {
    await api.post(`/api/connections/${c.id}`, { action, relation: action === "correct" ? rel : undefined, note: note || undefined });
    setEdit(false);
    onChange?.();
    toast(action === "dismiss" ? "Dismissed" : action === "restore" ? "Restored" : "Correction saved");
  };
  return (
    <div className={`conn ${c.status === "dismissed" ? "dismissed" : ""}`}>
      <div className="row">
        <span className={`conn-kind ${c.relation}`}>{RELATION_LABELS[c.relation]}</span>
        {c.status !== "active" && <span className="meta">· {c.status === "dismissed" ? "dismissed" : "corrected"} by you</span>}
      </div>
      {showNew && <div className="small" style={{ marginTop: 4 }}>From <RecordRef r={c.new} /></div>}
      <dl>
        <dt>Your record</dt><dd><RecordRef r={c.earlier} /></dd>
        <dt>What's new</dt><dd>{c.new_information}</dd>
        <dt>Why related</dt><dd>{c.why_related}</dd>
        <dt>Uncertain</dt><dd className="muted">{c.uncertain}</dd>
        {c.interpretation && <><dt>AI's view</dt><dd className="muted"><i>{c.interpretation}</i></dd></>}
        {c.user_correction && <><dt>Your note</dt><dd>{c.user_correction}</dd></>}
      </dl>
      {onChange && (
        <div className="row">
          {c.clinician_question && <SaveQuestion text={c.clinician_question} originKind="connection" originId={c.id} />}
          {c.status !== "dismissed" ? (
            <>
              <button className="btn ghost sm" onClick={() => setEdit(!edit)}>Correct</button>
              <button className="btn ghost sm" onClick={() => act("dismiss")}>Not relevant</button>
            </>
          ) : <button className="btn ghost sm" onClick={() => act("restore")}>Restore</button>}
        </div>
      )}
      {edit && (
        <div className="row" style={{ marginTop: 8 }}>
          <select className="select" value={rel} onChange={(e) => setRel(e.target.value)} aria-label="Relation">
            {Object.entries(RELATION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className="input grow" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note" aria-label="Correction note" />
          <button className="btn primary sm" onClick={() => act("correct")}>Save</button>
        </div>
      )}
    </div>
  );
}

export function SaveQuestion({ text, originKind, originId, label = "Save question for doctor" }: { text: string; originKind: string; originId?: number; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn sm" disabled={done} title={text} onClick={async () => {
      await api.post("/api/questions", { text, origin_kind: originKind, origin_id: originId });
      setDone(true);
      toast("Question saved for your next appointment");
    }}>{done ? "Saved" : label}</button>
  );
}

export function Sev({ n }: { n: number }) {
  return (
    <span className="sev" title={`Severity ${n} of 10`} aria-label={`Severity ${n} of 10`}>
      {Array.from({ length: 10 }, (_, i) => <i key={i} className={i < n ? "on" : ""} />)}
    </span>
  );
}

// ---------------------------------------------------------------- log a symptom (focused form)
export const COMMON_SYMPTOMS = ["fatigue", "brain fog", "dry eyes", "dry mouth", "joint pain", "muscle aches", "feeling cold", "trouble sleeping"];

export function SymptomDialog({ onClose, onSaved }: { onClose: () => void; onSaved?: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ symptom: "", occurred_on: today, severity: 5, duration: "", context: "", details: "" });
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  const [conn, setConn] = useState<string>("");
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const save = async () => {
    if (!f.symptom.trim()) return setErr("Choose or type a symptom.");
    try {
      const r = await api.post("/api/symptoms", f);
      setSaved(r.id);
      onSaved?.();
    } catch (e: any) { setErr(e.message); }
  };
  if (saved) {
    return (
      <Dialog title="Symptom saved" onClose={onClose}
        foot={<><button className="btn" onClick={onClose}>Done</button>{!conn && <button className="btn primary" onClick={async () => {
          setConn("Looking…");
          try { const r = await api.post(`/api/symptoms/${saved}/connect`); setConn(r.connections ? `${r.connections} related record(s) found — see the entry's video or note.` : r.message || "Nothing closely related."); }
          catch (e: any) { setConn(e.message); }
        }}>Find related videos and notes</button>}</>}>
        <p className="small muted">{conn || "UmmaCare can look for related videos and notes you saved before (uses AI)."}</p>
      </Dialog>
    );
  }
  return (
    <Dialog title="Log symptom" onClose={onClose} foot={<button className="btn primary" onClick={save}>Save</button>}>
      <div className="field">
        <label htmlFor="sym">What did you notice?</label>
        <input id="sym" className="input" list="symlist" value={f.symptom} onChange={(e) => set("symptom", e.target.value)} placeholder="e.g. fatigue" />
        <datalist id="symlist">{COMMON_SYMPTOMS.map((s) => <option key={s} value={s} />)}</datalist>
        <div className="row" style={{ marginTop: 8 }}>
          {COMMON_SYMPTOMS.slice(0, 5).map((s) => <button key={s} type="button" className="btn sm ghost" onClick={() => set("symptom", s)}>{s}</button>)}
        </div>
      </div>
      <div className="field">
        <label htmlFor="sev">How strong? <span className="hint">{f.severity} of 10</span></label>
        <input id="sev" type="range" min={0} max={10} value={f.severity} onChange={(e) => set("severity", +e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="sdate">Date</label>
        <input id="sdate" type="date" className="input" style={{ width: 180 }} value={f.occurred_on} onChange={(e) => set("occurred_on", e.target.value)} />
      </div>
      <details className="more">
        <summary>More details</summary>
        <div className="split" style={{ marginTop: 8 }}>
          <div className="field"><label htmlFor="dur">How long</label><input id="dur" className="input" value={f.duration} onChange={(e) => set("duration", e.target.value)} placeholder="all afternoon" /></div>
          <div className="field"><label htmlFor="ctx">What was going on</label><input id="ctx" className="input" value={f.context} onChange={(e) => set("context", e.target.value)} placeholder="after lunch" /></div>
        </div>
        <div className="field"><label htmlFor="det">Notes</label><textarea id="det" className="textarea" style={{ minHeight: 70 }} value={f.details} onChange={(e) => set("details", e.target.value)} /></div>
      </details>
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

// ---------------------------------------------------------------- new note (write / file / photo)
export function NoteDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (id: number) => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [mode, setMode] = useState<"write" | "file" | "photo">("write");
  const [f, setF] = useState<any>({ category: "symptom_observation", title: "", text: "", source: "typed", source_detail: "", recorded_on: today });
  const [img, setImg] = useState<any>(null);
  const [flags, setFlags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));
  const loadFile = async (file: File) => {
    setErr("");
    try {
      const r = await api.form("/api/notes/upload", { file });
      setF((p: any) => ({ ...p, text: r.text, title: p.title || r.title, source: r.source, source_detail: r.source_detail }));
      setFlags(r.flags || []);
    } catch (e: any) { setErr(e.message); }
  };
  const readPhoto = async (file: File) => {
    setErr(""); setBusy(true);
    try {
      const r = await api.form("/api/notes/image", { file });
      setImg(r);
      const x = r.extracted;
      setF((p: any) => ({ ...p, text: x.text, title: x.suggested_title, category: x.suggested_category, source: "image", source_detail: file.name }));
      setFlags(x.flags || []);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!f.title.trim() || !f.text.trim()) return setErr("Add a title and the note text.");
    try {
      const r = await api.post("/api/notes", { ...f, image_ref: img?.image_ref, extracted_text: img?.extracted?.text });
      toast("Note saved");
      onSaved(r.id);
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog title="New note" onClose={onClose} wide foot={<button className="btn primary" disabled={busy} onClick={save}>Save note</button>}>
      <div className="seg" role="tablist">
        {([["write", "Write"], ["file", "Text file"], ["photo", "Photo of a page"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{l}</button>
        ))}
      </div>
      {mode === "file" && <div className="field"><input type="file" accept=".txt,.md,.markdown" onChange={(e) => e.target.files?.[0] && loadFile(e.target.files[0])} /></div>}
      {mode === "photo" && (
        <div className="field">
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => e.target.files?.[0] && readPhoto(e.target.files[0])} />
          <div className="hint" style={{ marginTop: 6 }}>The photo is kept as is. Check the text the AI read; unreadable words are marked [illegible].</div>
          {busy && <p className="small muted" style={{ marginTop: 8 }}>Reading…</p>}
          {img && (
            <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
              <img src={img.image_url} alt="Original page" style={{ width: 140, borderRadius: 4, border: "1px solid var(--line)" }} />
              <div className="small muted grow">{img.extracted.reading_notes}{img.extracted.illegible_sections ? ` · ${img.extracted.illegible_sections} part(s) marked [illegible]` : ""}</div>
            </div>
          )}
        </div>
      )}
      <div className="field"><label htmlFor="nt">Title</label><input id="nt" className="input" value={f.title} onChange={(e) => set("title", e.target.value)} /></div>
      <div className="field">
        <label htmlFor="nx">{mode === "photo" ? "Text from the photo — please check" : "Note"}</label>
        <textarea id="nx" className="textarea" style={{ minHeight: 160 }} value={f.text} onChange={(e) => set("text", e.target.value)} />
      </div>
      <div className="split">
        <div className="field">
          <label htmlFor="nc">Kind</label>
          <select id="nc" className="select" style={{ width: "100%" }} value={f.category} onChange={(e) => set("category", e.target.value)}>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div className="field"><label htmlFor="nd">Date</label><input id="nd" type="date" className="input" value={f.recorded_on} onChange={(e) => set("recorded_on", e.target.value)} /></div>
      </div>
      {mode === "write" && <div className="field"><label htmlFor="ns">Source <span className="hint">optional, e.g. notebook p. 12</span></label><input id="ns" className="input" value={f.source_detail} onChange={(e) => set("source_detail", e.target.value)} /></div>}
      {f.category === "doctor_instruction" && <p className="hint">Saved as what you recorded a doctor said — not verified clinical guidance.</p>}
      {flags.length > 0 && <p className="notice warn">This text contains instruction-like sentences. They're kept as your note only and can't instruct the assistant.</p>}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}
