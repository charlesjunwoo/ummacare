# UmmaCare — a personal health-learning notebook with memory

UmmaCare is a quiet personal health journal for one person living with Hashimoto's disease and Sjögren's disease.

- **Calendar** (home): assistant drafts waiting for approval and today's appointments on top, then a month view
  (appointments, doctor's notes, symptoms), a symptom list, appointments with their true status, and the appointment brief.
- **Journal**: dated notes — typed, pasted, text/Markdown files, or photos of notebook pages (AI-read, reviewed).
- **Discovery**: paste a YouTube, article or Reddit link, paste a thread/article, or upload a photo/clipping → key takeaways,
  checked against NIH patient pages and connected to your notes. Articles are fetched only when the site allows it;
  Reddit threads are pasted in (Reddit blocks unregistered apps), usernames are removed, and community posts are labeled
  as personal experience. Links open Reddit searches in r/Hashimotos, r/thyroid, r/Hypothyroidism, r/Sjogrens,
  r/Autoimmune and r/Biohackers.
- **Records**: *Documents* (test results etc.; values copied exactly as written for review, never interpreted, original
  kept) and *Medication* (what you entered, schedule history, reminders, refill/supplement order requests).
- **Ask UmmaCare** (on every page): answers with separate citations for your records, Discovery items, and references. It
  can draft an appointment request or a refill/supplement order request — nothing is sent or bought until you approve it
  and do it yourself.


MGT 409 final project · Charles Park · Report: `report.html` · Slides: `slides.html`

> Not medical advice. UmmaCare does not diagnose, prescribe, or recommend treatment changes.

## Run it (about 3 minutes)

You need **Python 3.11+**, **Node.js 18+**, and **ffmpeg** (only for capturing frames from uploaded videos;
everything else works without it — `brew install ffmpeg` on a Mac).

1. Put your `.env` (with `PORTKEY_API_KEY=...`) **either in this folder or in the folder above it**. UmmaCare checks
   this folder first, then the parent. See `.env.example`.
2. From this folder run:

   ```bash
   ./start.sh
   ```

   The first run creates `backend/.venv`, installs packages, and builds the web app.
3. Open **http://127.0.0.1:8000**. (If port 8000 is busy: `PORT=8001 ./start.sh`.)

The first start loads **synthetic demo records** (invented notes, symptoms, medicines, appointments, all labeled
"Demo"). Remove them any time in *Settings & privacy*. AI features stay off until you agree to the consent dialog.

### Try the main workflow
1. **Discovery** → paste `https://www.youtube.com/watch?v=n3mOOb80aHE` → **Add video** → agree to AI use.
2. Watch the stages (captions → key takeaways → screenshots → connections), then **Open**.
3. On a takeaway: open “Related to your records”, correct or dismiss a connection, **Save**, or **Ask my doctor**.
4. **Records** → **Upload document** → `backend/data/fixtures/demo_lab_report.pdf` → **Copy details with AI** → check → save.
5. **Ask UmmaCare** (bottom right, any page): “What did my last thyroid blood test show?” or “Please order a refill of my levothyroxine.”
6. **Calendar → Appointment brief** → **Create brief** → Print / Download.
7. **Discovery → Paste a thread or article** → paste `backend/data/fixtures/reddit_thread_paste.txt`; or **Upload a photo or clipping** → `magazine_clipping.jpg`.

### Try real frame capture
YouTube does not allow downloading its videos, so UmmaCare captures frames only from a video **file you upload**.
A synthetic test lecture is included: Discovery → *Add a video without a YouTube link* → create an
entry → upload `backend/data/fixtures/demo_fatigue_lecture.vtt` as the caption file → upload
`backend/data/fixtures/demo_fatigue_lecture.mp4` under *Add real screenshots*.

### Developer mode (hot reload for the web app only)
```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000   # terminal 1 (no --reload on purpose)
cd frontend && npm run dev                                             # terminal 2, open http://127.0.0.1:5173
```
To stop, press Ctrl-C in each terminal (this stops the whole process; there are no worker children).

## Data, test data, and switching
- Your data lives in `backend/data/runtime/` (SQLite `ummacare.db` + uploaded media). It is git-ignored.
- Test/demo data lives in `backend/data/fixtures/` (all synthetic): `demo_records.json`, the demo lecture video and
  captions, `malicious_transcript.txt` (prompt-injection test), `handwritten_note.jpg`, `pharmacy_label.txt`, `demo_lab_report.pdf`, `reddit_thread_paste.txt`, `magazine_clipping.jpg`.
- Switch between data sets with `UMMACARE_DATA_DIR=/some/folder ./start.sh` (a new empty folder = a fresh notebook;
  demo records load on its first start). Settings has *Remove demo records*, *Export everything*, and *Delete all*.
- Medical references: `backend/data/references.json` — 21 verbatim passages from NIDDK (Hashimoto's) and NIAMS
  (Sjögren's), with URL, publisher, review date, retrieval date (2026-10-26), and passage ids.

## Evidence
`scripts/run_evidence.py` starts the real server on a fresh data folder and runs every workflow with the real model:
main workflow, uploaded-video frames, unavailable captions/frames, incorrect connections, unsupported claims,
malicious transcript, chat attacks, image notes, medication extraction, caching, request/budget limits, and
persistence across a restart. Results: `evidence/test_log.md`, `evidence/test_results.json`,
`evidence/usage_log.csv` (measured tokens/latency/cost), `evidence/appointment_brief.html`, `evidence/screenshots/`.

## How it is built
- **Frontend:** React + TypeScript + Vite (`frontend/`).
- **Backend:** FastAPI + SQLite with FTS5 full-text search (`backend/app/`).
- **AI:** PydanticAI, one main agent (`backend/app/agent.py`) on **gpt-6-luna** via Portkey (the only model the course
  key allows). Validated structured outputs; transcripts and notes are treated as untrusted data.
- **Deterministic code** (no AI): caption retrieval, transcript parsing, frame extraction (ffmpeg + Pillow
  legibility scoring), search, scheduling, dose logs, calendar (.ics) export, the brief's layout.

### Costs and limits
gpt-6-luna is priced at $0.10 / 1M input tokens, $0.01 / 1M cached input, $0.50 / 1M output (genai-prices data).
Each workflow run is capped (6 model requests, 60k tokens, 8 tool calls for chat), transcripts are truncated at
45k characters, and a **daily budget** (`DAILY_BUDGET_USD`, default $1.00) stops all AI calls once reached.

### What is not included (honest limits)
- **No speech-to-text.** If a video has no captions you paste or upload a transcript. Transcribing audio would need a
  separate paid service (e.g. a Whisper API) that the course key does not cover, so it was left out.
- **No YouTube downloads.** Frames come only from files you upload.
- **No real booking or purchasing.** The assistant drafts appointment and order requests; you approve them, then
  send/place them yourself, and mark "confirmed" / "ordered" only when that actually happened.
- Single user, local only, no login.
