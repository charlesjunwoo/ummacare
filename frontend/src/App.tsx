import { useEffect, useState } from "react";
import { api, onAiBlocked } from "./api";
import { AskPanel } from "./AskPanel";
import { ConsentDialog, ToastHost } from "./components";
import CalendarPage from "./pages/Calendar";
import { DiscoveryPage, SourceDetail } from "./pages/Discovery";
import { JournalPage, NoteDetail } from "./pages/Notes";
import { RecordDetail, RecordsPage } from "./pages/Records";
import SettingsPage from "./pages/Settings";

const HOME = "#/calendar";
// Older links keep working.
const ALIASES: Record<string, string> = { log: "calendar", videos: "discovery", brief: "calendar/brief" };

function useHash() {
  const [h, setH] = useState(window.location.hash || HOME);
  useEffect(() => {
    const f = () => { setH(window.location.hash || HOME); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h;
}

export default function App() {
  const hash = useHash();
  const parts = hash.replace(/^#/, "").split("/");
  let page: string = parts[1] || "", sub: string | undefined = parts[2];
  if (hash.startsWith("#/log/medicines")) { page = "records"; sub = "medication"; }
  else if (ALIASES[page]) { const t = ALIASES[page].split("/"); page = t[0]; sub = t[1] ?? sub; }
  const [status, setStatus] = useState<any>(null);
  const [consent, setConsent] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [tick, setTick] = useState(0);   // bumps when the assistant changes data, so pages reload
  const loadStatus = () => api.get("/api/status").then(setStatus).catch(() => setStatus({ offline: true }));
  useEffect(() => onAiBlocked((e) => { if (e.message.startsWith("AI features are off until")) setConsent(true); }), []);
  useEffect(() => { loadStatus(); }, [hash, tick]);
  useEffect(() => { if (page === "ask") { setAskOpen(true); window.location.hash = HOME; } }, [page]);

  const p = page || "calendar";
  const num = sub && /^\d+$/.test(sub);
  let body;
  switch (p) {
    case "journal": body = <JournalPage />; break;
    case "notes": body = sub ? <NoteDetail id={+sub} /> : <JournalPage />; break;
    case "discovery": body = num ? <SourceDetail id={+sub} /> : <DiscoveryPage />; break;
    case "records": body = num ? <RecordDetail id={+sub} /> : <RecordsPage tab={sub} />; break;
    case "settings": body = <SettingsPage onStatus={loadStatus} />; break;
    default: body = <CalendarPage tab={sub} tick={tick} />;
  }
  const section = p === "notes" ? "journal" : ["journal", "discovery", "records", "settings"].includes(p) ? p : "calendar";
  const Nav = ({ k, label, count }: { k: string; label: string; count?: number }) => (
    <a href={`#/${k}`} className={`nav-item ${section === k ? "active" : ""}`} aria-current={section === k ? "page" : undefined}>
      <span>{label}</span>{count ? <span className="nav-count" title={`${count} waiting for your approval`}>{count}</span> : null}
    </a>
  );
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">UmmaCare</div>
        <Nav k="calendar" label="Calendar" count={status?.pending_actions} />
        <Nav k="journal" label="Journal" />
        <Nav k="discovery" label="Discovery" />
        <Nav k="records" label="Records" />
        <div className="nav-group" />
        <Nav k="settings" label="Settings" />
        <div className="sidebar-foot">
          {status?.offline ? "Can't reach the app server." : status && <>AI {status.consent ? "on" : "off"}<br />Not medical advice.</>}
        </div>
      </nav>
      <main className="main" key={hash}>{body}</main>
      <AskPanel open={askOpen} setOpen={setAskOpen} onChange={() => setTick((t) => t + 1)} />
      {consent && <ConsentDialog onDone={() => { setConsent(false); loadStatus(); }} />}
      <ToastHost />
    </div>
  );
}
