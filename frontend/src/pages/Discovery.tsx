import { useEffect, useState } from "react";
import { api, fmtDate, go, VERDICT_LABELS } from "../api";
import { Connection, Dialog, Guide, Step, Steps } from "../components";

export const KIND_LABEL: Record<string, string> = { youtube: "Video", video_file: "Video", article: "Article", reddit: "Community thread", image: "Photo / clipping" };
const VOICE: Record<string, string> = { youtube: "The speaker says", video_file: "The speaker says", article: "The article says", reddit: "Commenters say", image: "The clipping says" };
const isVideo = (k: string) => k === "youtube" || k === "video_file";

// Runs the stages in order and reports each one honestly.
export async function processSource(id: number, kind: string, update: (s: Step[]) => void, base: Step[] = []) {
  const s: Step[] = [...base, { label: "Finding key takeaways", state: "run" }];
  if (isVideo(kind)) s.push({ label: "Screenshots", state: "todo" });
  s.push({ label: "Connecting to your notes", state: "todo" });
  const iTake = base.length, iShot = isVideo(kind) ? base.length + 1 : -1, iConn = s.length - 1;
  update([...s]);
  try {
    const a = await api.post(`/api/videos/${id}/analyze`);
    s[iTake] = { label: "Key takeaways", state: "done", detail: a.cached ? "reused, text unchanged" : undefined };
    if (iShot >= 0) s[iShot] = a.frames.captured > 0
      ? { label: "Screenshots", state: "done", detail: `${a.frames.captured} captured from your video file` }
      : { label: "Screenshots", state: "warn", detail: "unavailable without your own video file" };
    s[iConn] = { label: "Connecting to your notes", state: "run" };
    update([...s]);
    const c = await api.post(`/api/videos/${id}/connect`);
    s[iConn] = { label: "Connected to your notes", state: "done", detail: `${c.connections} connection${c.connections === 1 ? "" : "s"}` };
    update([...s]);
    return true;
  } catch (e: any) {
    const i = s.findIndex((x) => x.state === "run");
    s[i] = { ...s[i], state: "fail", detail: e.message };
    update([...s]);
    return false;
  }
}

function thumbFor(v: any): string | null {
  if (v.frame) return `/media/${v.frame}`;
  if (v.image_path) return `/media/${v.image_path}`;
  if (v.youtube_id) return `https://i.ytimg.com/vi/${v.youtube_id}/mqdefault.jpg`;
  return null;
}
const thumbText = (v: any) => (v.kind === "reddit" ? (v.title.match(/r\/\w+/)?.[0] || "Thread") : v.kind === "article" ? (v.site || "Article") : "No preview");

export function DiscoveryPage() {
  const [items, setItems] = useState<any[] | null>(null);
  const [url, setUrl] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  const [newId, setNewId] = useState<number | null>(null);
  const [kind, setKind] = useState("");
  const [paste, setPaste] = useState(false);
  const [photo, setPhoto] = useState(false);
  const [videoFile, setVideoFile] = useState(false);
  const load = () => api.get("/api/videos").then(setItems);
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!url.trim()) return;
    setBusy(true); setNewId(null);
    setSteps([{ label: "Reading the link", state: "run" }]);
    try {
      const r = await api.post("/api/sources/link", { url });
      const v = r.video;
      setNewId(v.id);
      const base: Step[] = r.stages.filter((x: any) => x.stage !== "link").map((x: any) => ({
        label: x.stage === "already_added" ? "Already in Discovery" : x.stage === "captions" ? "Captions" : x.stage === "safety" ? "Instruction-like text flagged" : "Text",
        state: x.warn ? "warn" : x.ok ? "done" : "fail",
        detail: x.stage === "captions" && x.ok ? "existing YouTube captions, not a new transcription" : x.ok ? x.detail : (x.detail || "").split(". You can")[0] + ". Open it to paste the text.",
      }));
      setSteps(base);
      if (v.status === "transcript_ready") await processSource(v.id, v.kind, setSteps, base);
      setUrl("");
      load();
    } catch (e: any) {
      setSteps([{ label: "Couldn't add this link", state: "fail", detail: e.message }]);
    } finally { setBusy(false); }
  };
  const shown = (items || []).filter((v) => !kind || (kind === "video" ? isVideo(v.kind) : v.kind === kind));

  return (
    <div className="page">
      <div className="head">
        <div><h1>Discovery</h1></div>
      </div>
      <Guide>Paste a link to a YouTube video, article or Reddit thread to get its key takeaways · Paste text or upload a photo when a link can't be read · Open one to see how it relates to your notes.</Guide>
      <div className="row">
        <input className="input grow" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Paste a video, article or Reddit link" aria-label="Link" />
        <button className="btn primary" disabled={busy || !url.trim()} onClick={add}>{busy ? "Working…" : "Add"}</button>
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <button className="btn ghost sm" onClick={() => setPaste(true)}>Paste text instead</button>
        <button className="btn ghost sm" onClick={() => setPhoto(true)}>Upload a photo or clipping</button>
        <button className="btn ghost sm" onClick={() => setVideoFile(true)}>Add a video without a YouTube link</button>
      </div>
      {steps.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <Steps steps={steps} />
          {newId && !busy && <a className="btn sm" style={{ marginTop: 8 }} href={`#/discovery/${newId}`}>Open</a>}
        </div>
      )}

      <Communities />

      <div className="row" style={{ justifyContent: "space-between", marginTop: 24 }}>
        <div className="date-head" style={{ padding: 0 }}>Saved</div>
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by type">
          <option value="">Everything</option><option value="video">Videos</option><option value="article">Articles</option><option value="reddit">Community threads</option><option value="image">Photos and clippings</option>
        </select>
      </div>
      <ul className="list" style={{ marginTop: 8 }}>
        {shown.map((v) => (
          <li key={v.id}>
            <a className="item" href={`#/discovery/${v.id}`}>
              <div className="thumb">{thumbFor(v) ? <img src={thumbFor(v)!} alt="" loading="lazy" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} /> : thumbText(v)}</div>
              <div className="grow">
                <div className="item-title">{v.title || "Untitled"}</div>
                <div className="meta">{[KIND_LABEL[v.kind], v.channel || v.site || (v.kind === "image" ? "your photo" : v.kind === "video_file" ? "uploaded" : ""), `added ${fmtDate(v.created_at)}`].filter(Boolean).join(" · ")}</div>
                <div className="item-preview" style={{ whiteSpace: "normal", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as any }}>
                  {v.summary || (v.status === "needs_transcript" ? "Needs text — open to paste it." : "Not processed yet.")}
                </div>
                {v.moments?.length > 0 && <div className="meta" style={{ marginTop: 2 }}>{v.moments.length} key takeaways{v.connections ? ` · ${v.connections} connections` : ""}</div>}
              </div>
            </a>
          </li>
        ))}
      </ul>
      {items && shown.length === 0 && <p className="empty">Nothing here yet.</p>}
      {paste && <PasteDialog onClose={() => setPaste(false)} />}
      {photo && <PhotoDialog onClose={() => setPhoto(false)} />}
      {videoFile && <VideoFileDialog onClose={() => setVideoFile(false)} />}
    </div>
  );
}

// Reddit can't be read automatically; this opens Reddit's own search in her browser.
function Communities() {
  const [subs, setSubs] = useState<string[]>([]);
  const [topic, setTopic] = useState("fatigue");
  useEffect(() => { api.get("/api/sources/communities").then(setSubs); }, []);
  const q = encodeURIComponent(`${topic} (hashimoto OR hashimotos OR sjogren OR sjogrens OR thyroid)`.trim());
  return (
    <details className="more" style={{ marginTop: 16 }}>
      <summary>Find community threads on Reddit</summary>
      <div style={{ paddingLeft: 14 }}>
        <p className="meta">Opens Reddit in your browser. Copy a useful thread and add it with “Paste text instead”. UmmaCare removes usernames, and treats what people share as personal experience, not evidence.</p>
        <div className="row">
          <input className="input" style={{ width: 220 }} value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Topic" placeholder="Topic, e.g. fatigue" />
          {subs.map((s) => <a key={s} className="btn sm ghost" target="_blank" rel="noreferrer" href={`https://www.reddit.com/r/${s}/search/?q=${q}&restrict_sr=1&sort=relevance&t=year`}>r/{s}</a>)}
        </div>
      </div>
    </details>
  );
}

function PasteDialog({ onClose, into }: { onClose: () => void; into?: any }) {
  const [f, setF] = useState({ kind: into?.kind || "reddit", title: into?.title || "", url: into?.source_url || "", text: "" });
  const [steps, setSteps] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.post("/api/sources/text", { ...f, url: f.url || null, video_id: into?.id });
      const base: Step[] = [{ label: "Text saved", state: "done", detail: `${r.segments} paragraphs${f.kind === "reddit" ? ", usernames removed" : ""}` }];
      if (r.injection_flags?.length) base.push({ label: "Instruction-like text flagged", state: "warn", detail: "treated as content only" });
      await processSource(r.video.id, r.video.kind, setSteps, base);
      go(`#/discovery/${r.video.id}`);
      onClose();
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <Dialog title={into ? "Paste the text" : "Paste a thread or article"} wide onClose={onClose}
      foot={<button className="btn primary" disabled={busy || f.text.trim().length < 40 || !f.title.trim()} onClick={save}>{busy ? "Working…" : "Save and summarize"}</button>}>
      {!into && (
        <div className="split">
          <div className="field"><label htmlFor="pk">Type</label>
            <select id="pk" className="select" style={{ width: "100%" }} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="reddit">Community thread (Reddit)</option><option value="article">Article</option>
            </select></div>
          <div className="field"><label htmlFor="pt">Title</label><input id="pt" className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. r/Hashimotos — afternoon fatigue" /></div>
        </div>
      )}
      {!into && <div className="field"><label htmlFor="pu">Link <span className="hint">optional</span></label><input id="pu" className="input" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…" /></div>}
      <div className="field">
        <label htmlFor="px">Text</label>
        <textarea id="px" className="textarea" style={{ minHeight: 200 }} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })}
          placeholder={f.kind === "reddit" ? "Select the post and comments on the Reddit page, copy, and paste here." : "Paste the article text."} />
      </div>
      {steps.length > 0 && <Steps steps={steps} />}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

function PhotoDialog({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [err, setErr] = useState("");
  const upload = async (file: File) => {
    setErr("");
    setSteps([{ label: "Reading the photo", state: "run" }]);
    try {
      const r = await api.form("/api/sources/image", { file, title });
      if (r.warning) { setSteps([{ label: "Photo saved", state: "warn", detail: r.warning }]); return; }
      const base: Step[] = [{ label: "Text read from the photo", state: "done", detail: `${r.segments} lines` }];
      await processSource(r.video.id, "image", setSteps, base);
      go(`#/discovery/${r.video.id}`);
      onClose();
    } catch (e: any) { setSteps([]); setErr(e.message); }
  };
  return (
    <Dialog title="Upload a photo or clipping" onClose={onClose}>
      <p className="small muted">A magazine cutout, a leaflet, or a screenshot of a post. The photo is kept as is and its text is read for takeaways.</p>
      <div className="field"><label htmlFor="ph">Title <span className="hint">optional</span></label><input id="ph" className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
      <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      {steps.length > 0 && <Steps steps={steps} />}
      {err && <div className="error">{err}</div>}
    </Dialog>
  );
}

function VideoFileDialog({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState("");
  return (
    <Dialog title="Add a video without a YouTube link" onClose={onClose}
      foot={<button className="btn primary" disabled={!title.trim()} onClick={async () => { const r = await api.form("/api/videos/manual", { title }); go(`#/discovery/${r.video.id}`); onClose(); }}>Create</button>}>
      <p className="small muted">Create the entry, then add its transcript (paste or caption file) and, if you have it, the video file for real screenshots.</p>
      <div className="field"><label htmlFor="vt">Title</label><input id="vt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
    </Dialog>
  );
}

const fmtT = (s: number) => (s < 0 ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);

export function SourceDetail({ id }: { id: number }) {
  const [v, setV] = useState<any>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  const [paste, setPaste] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api.get(`/api/videos/${id}`).then(setV).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]);
  if (err && !v) return <div className="page"><p className="error">{err}</p></div>;
  if (!v) return null;
  const video = isVideo(v.kind);

  const uploadVideo = async (file: File) => {
    setErr(""); setBusy(true);
    setSteps([{ label: `Uploading ${file.name}`, state: "run" }]);
    try {
      const r = await api.form(`/api/videos/${id}/media`, { file });
      setSteps([{ label: "Video file stored on this computer", state: "done" }, { label: "Screenshots", state: r.captured ? "done" : "warn", detail: r.captured ? `${r.captured} captured` : "captured after the text is processed" }]);
      await load();
    } catch (e: any) { setSteps([{ label: "Upload failed", state: "fail", detail: e.message }]); } finally { setBusy(false); }
  };
  const needs = v.status === "needs_transcript" || v.transcript_source === "none";
  const original = v.url || v.source_url;

  return (
    <div className="page">
      <a className="back" href="#/discovery">← Discovery</a>
      <div className="meta">{KIND_LABEL[v.kind]} · {v.channel || v.site || "your photo"} · {v.transcript_note || "no text yet"}</div>
      <div className="head" style={{ marginTop: 4 }}>
        <h1>{v.title || "Untitled"}</h1>
        {original && <a className="btn" href={original} target="_blank" rel="noreferrer">Open original</a>}
      </div>
      <Guide>Key takeaways from this {KIND_LABEL[v.kind].toLowerCase()} · Open “Related to your records” to see what it connects to · “Not relevant” removes a wrong match.</Guide>
      {v.kind === "reddit" && <p className="notice" style={{ marginBottom: 16 }}>People's personal experiences — useful for questions, not evidence. Usernames were removed.</p>}
      {v.image_path && <img src={`/media/${v.image_path}`} alt="Your photo" style={{ width: 260, borderRadius: 6, border: "1px solid var(--line)", marginBottom: 16 }} />}
      {v.summary && <><div className="voice">{v.kind === "reddit" ? "What the thread covers" : "What it says"}</div><p className="prose">{v.summary}</p></>}
      {v.injection_flags?.length > 0 && (
        <details className="more notice warn">
          <summary>This text contains instruction-like sentences. They were treated as content only.</summary>
          <ul className="small">{v.injection_flags.map((f: string, i: number) => <li key={i}>“{f}”</li>)}</ul>
        </details>
      )}
      {steps.length > 0 && <Steps steps={steps} />}

      {needs && (
        <div className="section">
          <h2>Add the text</h2>
          <p className="small muted">{v.status_detail || "No text yet."} UmmaCare won't summarize from a title or link alone.</p>
          <div className="row">
            <button className="btn primary" onClick={() => setPaste(true)}>Paste text</button>
            {video && <label className="btn">Upload .srt / .vtt / .txt<input type="file" accept=".srt,.vtt,.txt" className="sr-only" onChange={async (e) => {
              const file = e.target.files?.[0]; if (!file) return;
              setBusy(true);
              try { const r = await api.form(`/api/videos/${id}/transcript`, { file, text: "" }); await processSource(id, v.kind, setSteps, [{ label: "Transcript received", state: "done", detail: `${r.segments} lines` }]); await load(); }
              catch (er: any) { setErr(er.message); } finally { setBusy(false); }
            }} /></label>}
          </div>
          {err && <div className="error">{err}</div>}
        </div>
      )}

      {v.moments_full.length > 0 && (
        <div className="section">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>Key takeaways</h2>
            <button className="btn ghost sm" disabled={busy} onClick={async () => { setBusy(true); await processSource(id, v.kind, setSteps); await load(); setBusy(false); }}>Re-check connections</button>
          </div>
          {v.moments_full.map((m: any) => <Takeaway key={m.id} m={m} kind={v.kind} reload={load} />)}
        </div>
      )}

      <hr className="div" />
      {video && !v.media_path && (
        <details className="more">
          <summary>Add screenshots from your own copy of this video</summary>
          <p className="small muted" style={{ paddingLeft: 14 }}>UmmaCare doesn't download from YouTube. If you have the video file, upload it and real frames are captured at each takeaway.</p>
          <input style={{ marginLeft: 14 }} type="file" accept="video/*" disabled={busy} onChange={(e) => e.target.files?.[0] && uploadVideo(e.target.files[0])} />
        </details>
      )}
      {v.segments.length > 0 && (
        <details className="more">
          <summary>{video ? "Full transcript" : "Full text"}</summary>
          <div className="transcript" style={{ paddingLeft: 14 }}>
            {v.segments.map((s: any) => (
              <p key={s.idx}>{s.start >= 0 && <span className="ts">{v.youtube_id ? <a href={`https://www.youtube.com/watch?v=${v.youtube_id}&t=${Math.floor(s.start)}s`} target="_blank" rel="noreferrer">{fmtT(s.start)}</a> : fmtT(s.start)}</span>}{s.text}</p>
            ))}
          </div>
        </details>
      )}
      <details className="more">
        <summary>More</summary>
        <div style={{ paddingLeft: 14 }}>
          <span className="meta">Added {fmtDate(v.created_at)}. </span>
          <button className="btn danger sm" onClick={async () => { if (confirm("Delete this from Discovery?")) { await api.del(`/api/videos/${id}`); go("#/discovery"); } }}>Delete</button>
        </div>
      </details>
      {paste && <PasteDialog into={v} onClose={() => { setPaste(false); load(); }} />}
    </div>
  );
}

function Takeaway({ m, kind, reload }: { m: any; kind: string; reload: () => void }) {
  const nConn = m.connections.filter((c: any) => c.status !== "dismissed").length + m.incoming.length;
  const video = isVideo(kind);
  const body = (
    <div>
      <h3>{m.heading}</h3>
      <div className="voice">{VOICE[kind]}{m.link && video ? <> · <a href={m.link} target="_blank" rel="noreferrer">{m.time}</a></> : video && m.time ? ` · ${m.time}` : ""}</div>
      <p className="small">{m.explanation}</p>
      <details className="more"><summary>Exact words</summary><div className="quote small">{m.excerpt}</div></details>
      {m.claim_checks.length > 0 && (
        <details className="more">
          <summary>Checked against medical references ({m.claim_checks.filter((k: any) => k.verdict === "supports").length} supported, {m.claim_checks.filter((k: any) => k.verdict !== "supports").length} not)</summary>
          <div style={{ paddingLeft: 14 }}>
            {m.claim_checks.map((k: any) => (
              <div key={k.id} className="small" style={{ marginBottom: 10 }}>
                <div><span className={`tag ${k.verdict === "supports" ? "green" : "warn"}`}>{VERDICT_LABELS[k.verdict]}</span> — “{k.claim}”</div>
                <div className="muted">{k.explanation}</div>
                {k.reference && <div className="meta"><a href={k.reference.url} target="_blank" rel="noreferrer">{k.reference.publisher.match(/\((\w+)\)/)?.[1]}: {k.reference.section}</a> · reviewed {k.reference.reviewed} · {k.reference.id}</div>}
              </div>
            ))}
            <p className="meta">“Not established” means the saved references don't address it — not that it's false.</p>
          </div>
        </details>
      )}
      <details className="more" open={m.connections.some((c: any) => c.relation === "conflicts")}>
        <summary>Related to your records ({nConn})</summary>
        <div style={{ paddingLeft: 14 }}>
          {nConn === 0 && <p className="meta">Nothing related found.</p>}
          {m.connections.map((c: any) => <Connection key={c.id} c={c} onChange={reload} askDoctor={false} />)}
          {m.incoming.map((c: any) => <Connection key={"in" + c.id} c={c} showNew onChange={reload} askDoctor={false} />)}
        </div>
      </details>
    </div>
  );
  if (!video) return <article style={{ padding: "24px 0", borderTop: "1px solid var(--line)" }}>{body}</article>;
  return (
    <article className="moment">
      <div>
        <div className="frame">
          {m.frame_status === "captured" ? <img src={`/media/${m.frame_path}`} alt={`Frame at ${m.time}`} /> : <div className="frame-none">Frame unavailable</div>}
        </div>
        <div className="meta" style={{ marginTop: 6 }}>{m.frame_status === "captured" ? `Real frame from your video file, ${fmtT(m.frame_time)}` : "Text only — no video file"}</div>
      </div>
      {body}
    </article>
  );
}
