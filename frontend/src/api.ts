// Tiny fetch wrapper. Errors carry the backend's readable `detail` and `kind`
// (e.g. kind === "ai_blocked" opens the consent dialog).

export class ApiError extends Error {
  kind?: string;
  status: number;
  constructor(message: string, status: number, kind?: string) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

type Listener = (e: ApiError) => void;
const blockedListeners = new Set<Listener>();
export const onAiBlocked = (fn: Listener) => {
  blockedListeners.add(fn);
  return () => {
    blockedListeners.delete(fn);
  };
};

async function request<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(path, init);
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    let msg = data?.detail ?? `Something went wrong (${res.status}).`;
    if (Array.isArray(msg)) msg = msg.map((d: any) => d.msg).join("; ");
    const err = new ApiError(String(msg), res.status, data?.kind);
    if (err.kind === "ai_blocked") blockedListeners.forEach((fn) => fn(err));
    throw err;
  }
  return data as T;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T = any>(p: string, b?: unknown) => request<T>("PUT", p, b),
  patch: <T = any>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  form: <T = any>(p: string, fields: Record<string, string | Blob | undefined>) => {
    const fd = new FormData();
    Object.entries(fields).forEach(([k, v]) => v !== undefined && fd.append(k, v));
    return request<T>("POST", p, fd);
  },
};

export const CATEGORY_LABELS: Record<string, string> = {
  symptom_observation: "Symptom observation",
  video_or_article: "Video or article note",
  diet_lifestyle: "Diet or lifestyle note",
  doctor_instruction: "Doctor's instruction",
  personal_question: "Personal question",
};

export const RELATION_LABELS: Record<string, string> = {
  repeats: "Repeats something you saved",
  adds_detail: "Adds detail",
  conflicts: "Disagrees with something you saved",
  related: "Related topic",
};

export const VERDICT_LABELS: Record<string, string> = {
  supports: "Reference supports this",
  contradicts: "Reference disagrees",
  not_established: "Not established by the saved references",
};

export function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDateTime(iso?: string | null) {
  if (!iso) return "Time not set";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function go(hash: string) {
  window.location.hash = hash;
}

export const DOC_TYPES: Record<string, string> = {
  lab_result: "Test result",
  visit_summary: "Visit summary",
  imaging_report: "Imaging report",
  prescription: "Prescription",
  other: "Other",
};

export const SOURCE_LABELS: Record<string, string> = {
  typed: "Typed",
  pasted: "Pasted",
  text_upload: "Text file",
  markdown_upload: "Markdown file",
  image: "Photo",
};
