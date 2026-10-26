import { useEffect, useState } from "react";
import { api, DOC_TYPES, fmtDate, go } from "../api";
import { Dialog, Guide, toast } from "../components";
import Medication from "./Medication";

export function RecordsPage({ tab = "documents" }: { tab?: string }) {
  const [docs, setDocs] = useState<any[] | null>(null);
  const [type, setType] = useState("");
  const [uploading, setUploading] = useState(false);
  useEffect(() => { api.get("/api/documents").then(setDocs); }, []);
  const shown = (docs || []).filter((d) => !type || d.doc_type === type);
  return (
    <div className="page">
      <div className="head">
        <div><h1>Records</h1></div>
        {tab !== "medication" && <button className="btn primary" onClick={() => setUploading(true)}>Upload document</button>}
      </div>
      <Guide>“Upload document” keeps a test result or report and copies its numbers for you to check · Medication lists your medicines and refill requests.</Guide>
      <nav className="seg" aria-label="Records sections">
        <a href="#/records" className={tab !== "medication" ? "on" : ""}>Documents</a>
        <a href="#/records/medication" className={tab === "medication" ? "on" : ""}>Medication</a>
      </nav>
      {tab === "medication" ? <Medication /> : <>
      <div className="row" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
        <select className="select" value={type} onChange={(e) => setType(e.target.value)} aria-label="Filter by type">
          <option value="">All records</option>{Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {docs && shown.length === 0 && <p className="empty">No records yet. Upload a PDF or a photo of a document.</p>}
      <ul className="list">
        {shown.map((d) => (
          <li key={d.id}>
            <a className="item" href={`#/records/${d.id}`}>
              <div className="paper" aria-hidden>{d.mime.startsWith("image/") && <img src={`/media/${d.file_path}`} alt="" />}</div>
              <div className="grow">
                <div className="item-title">{d.title.replace("[Demo] ", "")}</div>
                <div className="item-preview">{d.results.length ? d.results.slice(0, 4).map((r: any) => `${r.test} ${r.value}${r.unit ? " " + r.unit : ""}`).join(" · ") : d.provider || d.original_name}</div>
                <div className="meta">{d.document_date ? fmtDate(d.document_date) : "No date"} · {DOC_TYPES[d.doc_type]}{d.status !== "reviewed" ? " · not reviewed yet" : ""}{d.is_demo ? " · demo" : ""}</div>
              </div>
            </a>
          </li>
        ))}
      </ul>
      </>}
      {uploading && <UploadDialog onClose={() => setUploading(false)} />}
    </div>
  );
}

function UploadDialog({ onClose }: { onClose: () => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const upload = async (file: File) => {
    setBusy(true); setErr("");
    try { const d = await api.form("/api/documents/upload", { file }); go(`#/records/${d.id}`); onClose(); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <Dialog title="Upload a document" onClose={onClose}>
      <p className="small muted">PDF or photo (JPG, PNG). The original file is kept unchanged on this computer.</p>
      <input type="file" accept=".pdf,image/png,image/jpeg,image/webp" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      {busy && <p className="small muted">Uploading…</p>}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

export function RecordDetail({ id }: { id: number }) {
  const [d, setD] = useState<any>(null);
  const [form, setForm] = useState<any>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api.get(`/api/documents/${id}`).then((x) => {
    setD(x);
    setForm({ title: x.title, doc_type: x.doc_type, document_date: x.document_date || "", provider: x.provider || "", extracted_text: x.extracted_text || "", results: x.results, read_by: x.read_by, notes: x.notes || "" });
  });
  useEffect(() => { load(); }, [id]);
  if (!d || !form) return null;
  const editing = d.status !== "reviewed" || form._edit;
  const set = (k: string, v: any) => setForm({ ...form, [k]: v });
  const read = async () => {
    setBusy(true); setErr("");
    try {
      const p = (await api.post(`/api/documents/${id}/read`)).proposal;
      setForm({ ...form, title: p.title, doc_type: p.doc_type, document_date: p.document_date, provider: p.provider, extracted_text: p.text, results: p.results, read_by: p.read_by, _notes: p.reading_notes, _flags: p.flags });
      setReviewed(false);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const save = async () => {
    setErr("");
    try { await api.put(`/api/documents/${id}`, { ...form, document_date: form.document_date || null, reviewed }); toast("Record saved"); setReviewed(false); load(); }
    catch (e: any) { setErr(e.message); }
  };
  const setRes = (i: number, k: string, v: string) => set("results", form.results.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)));
  const aiRead = ["ai_image", "ai_text", "pdf_text"].includes(form.read_by);

  return (
    <div className="page wide">
      <a className="back" href="#/records">← Records</a>
      <div className="meta">{DOC_TYPES[d.doc_type]} · {d.document_date ? fmtDate(d.document_date) : "no date"}{d.provider ? ` · ${d.provider}` : ""}</div>
      <div className="head" style={{ marginTop: 4 }}>
        <h1>{d.title.replace("[Demo] ", "")}</h1>
        <a className="btn" href={d.url} target="_blank" rel="noreferrer">Open original</a>
      </div>
      <Guide>Your original file is on the left · The numbers are copied exactly as written — ask your clinician what they mean for you.</Guide>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 32 }} className="rec-grid">
        <div>
          {d.mime === "application/pdf"
            ? <iframe title="Original document" src={d.url} style={{ width: "100%", height: 560, border: "1px solid var(--line)", borderRadius: 6, background: "#fff" }} />
            : <img src={d.url} alt="Original document" style={{ width: "100%", borderRadius: 6, border: "1px solid var(--line)" }} />}
          <div className="meta" style={{ marginTop: 6 }}>Original file, kept unchanged · {d.original_name}</div>
        </div>
        <div>
          {!editing ? (
            <>
              {d.results.length > 0 && (
                <>
                  <div className="voice" style={{ marginTop: 0 }}>Results as written in the document</div>
                  <table className="data">
                    <thead><tr><th>Test</th><th>Result</th><th>Range</th><th>Flag</th></tr></thead>
                    <tbody>{d.results.map((r: any, i: number) => <tr key={i}><td>{r.test}</td><td>{r.value} {r.unit}</td><td className="muted">{r.reference_range}</td><td>{r.flag_as_written}</td></tr>)}</tbody>
                  </table>
                  <p className="meta">Copied, not interpreted. Ask your clinician what these mean for you.</p>
                </>
              )}
              {d.extracted_text && <details className="more"><summary>Text from the document</summary><p className="prose small" style={{ paddingLeft: 14 }}>{d.extracted_text}</p></details>}
              {d.notes && <><div className="voice">Your notes</div><p className="small">{d.notes}</p></>}
              <div className="row" style={{ marginTop: 16 }}>
                <button className="btn sm" onClick={() => setForm({ ...form, _edit: true })}>Edit</button>
                <button className="btn danger sm" onClick={async () => { if (confirm("Delete this record and its file?")) { await api.del(`/api/documents/${id}`); go("#/records"); } }}>Delete</button>
              </div>
            </>
          ) : (
            <>
              {d.status !== "reviewed" && !aiRead && (
                <div className="notice" style={{ marginBottom: 16 }}>
                  Fill in the details yourself, or have them copied from the document for you to check.
                  <div style={{ marginTop: 8 }}><button className="btn sm primary" disabled={busy} onClick={read}>{busy ? "Reading…" : "Copy details from the document"}</button></div>
                </div>
              )}
              {aiRead && d.status !== "reviewed" && <p className="notice warn" style={{ marginBottom: 16 }}>Copied{form.read_by === "pdf_text" ? " from the PDF text (values checked against it)" : " from the image"}. Compare with the original before saving.{form._notes ? ` ${form._notes}` : ""}</p>}
              {form._flags?.length > 0 && <p className="notice warn">This document contains instruction-like text; it was treated as content only.</p>}
              <div className="field"><label htmlFor="dt">Title</label><input id="dt" className="input" value={form.title} onChange={(e) => set("title", e.target.value)} /></div>
              <div className="split">
                <div className="field"><label htmlFor="dk">Type</label><select id="dk" className="select" style={{ width: "100%" }} value={form.doc_type} onChange={(e) => set("doc_type", e.target.value)}>{Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
                <div className="field"><label htmlFor="dd">Date on document</label><input id="dd" type="date" className="input" value={form.document_date} onChange={(e) => set("document_date", e.target.value)} /></div>
              </div>
              <div className="field"><label htmlFor="dp">Lab or clinic</label><input id="dp" className="input" value={form.provider} onChange={(e) => set("provider", e.target.value)} /></div>
              <div className="label">Results <span className="hint">as written</span></div>
              <table className="data">
                <thead><tr><th>Test</th><th>Value</th><th>Unit</th><th>Range</th><th>Flag</th><th /></tr></thead>
                <tbody>{form.results.map((r: any, i: number) => (
                  <tr key={i}>{["test", "value", "unit", "reference_range", "flag_as_written"].map((k) => <td key={k}><input className="input" value={r[k] || ""} onChange={(e) => setRes(i, k, e.target.value)} aria-label={k} /></td>)}
                    <td><button className="btn ghost sm" aria-label="Remove row" onClick={() => set("results", form.results.filter((_: any, j: number) => j !== i))}>×</button></td></tr>))}</tbody>
              </table>
              <button className="btn ghost sm" onClick={() => set("results", [...form.results, { test: "", value: "", unit: "", reference_range: "", flag_as_written: "" }])}>Add row</button>
              <details className="more"><summary>Full text and your notes</summary>
                <div className="field"><label htmlFor="dx">Text</label><textarea id="dx" className="textarea" value={form.extracted_text} onChange={(e) => set("extracted_text", e.target.value)} /></div>
                <div className="field"><label htmlFor="dn">Your notes</label><textarea id="dn" className="textarea" style={{ minHeight: 60 }} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>
              </details>
              {aiRead && <label className="check" style={{ marginTop: 12 }}><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I compared these details with the original</label>}
              {err && <div className="error">{err}</div>}
              <div className="row" style={{ marginTop: 16 }}>
                <button className="btn primary" onClick={save}>Save record</button>
                {form._edit && <button className="btn" onClick={() => load()}>Cancel</button>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
