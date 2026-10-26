"""Turn measured usage (evidence/usage_log.csv) into per-run and per-user-month costs.
Only rows that reached the model are averaged (ok=1, cache_hit=0, requests>0). Assumptions are explicit below.
Writes evidence/tokenomics.json and prints a table."""

from __future__ import annotations

import csv
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.10, 0.01, 0.50   # USD per 1M tokens, gpt-6-luna (genai-prices)

# Monthly activity of one ACTIVE user (assumption; Umma-style use: ~2 videos a week, a note most days).
MONTHLY = {
    "analyze_video": 10,      # new Discovery items (videos, articles, threads, clippings)
    "connect_video": 12,      # 10 new + 2 re-checks
    "connect_record": 15,     # notes/symptoms she asks to connect
    "chat": 30,               # questions to the assistant
    "draft_brief": 2,         # AI-drafted appointment briefs
    "read_note_image": 3,     # photos of handwritten notes
    "extract_medication": 1,  # medication label copies
    "read_document": 2,       # medical documents (test results) copied for review
}


def main():
    rows = list(csv.DictReader(open(ROOT / "evidence" / "usage_log.csv")))
    real = [r for r in rows if r["ok"] == "1" and r["cache_hit"] == "0" and int(r["requests"] or 0) > 0]
    hits = [r for r in rows if r["cache_hit"] == "1"]
    per = {}
    for wf in MONTHLY:
        rs = [r for r in real if r["workflow"] == wf]
        if not rs:
            continue
        f = lambda k: [float(r[k] or 0) for r in rs]
        per[wf] = {"runs_measured": len(rs), "avg_input": round(st.mean(f("input_tokens"))), "avg_cached_input": round(st.mean(f("cached_tokens"))),
                   "avg_output": round(st.mean(f("output_tokens"))), "avg_requests": round(st.mean(f("requests")), 2),
                   "median_latency_s": round(st.median(f("latency_ms")) / 1000, 1), "avg_cost_usd": st.mean(f("cost_usd"))}
    month = sum(per[w]["avg_cost_usd"] * n for w, n in MONTHLY.items() if w in per)
    month_tokens = {k: sum(per[w][k] * n for w, n in MONTHLY.items() if w in per) for k in ("avg_input", "avg_cached_input", "avg_output")}
    session = sum(per[w]["avg_cost_usd"] for w in ("analyze_video", "connect_video")) + per["chat"]["avg_cost_usd"] * 2
    out = {"prices_per_million": {"input": PRICE_IN, "cached_input": PRICE_CACHED, "output": PRICE_OUT},
           "per_workflow": per, "monthly_activity_assumption": MONTHLY,
           "typical_video_session_usd": round(session, 5),
           "per_user_month_usd": round(month, 4), "per_user_month_tokens": month_tokens,
           "users_100_month_usd": round(month * 100, 2), "users_10000_month_usd": round(month * 10_000, 2),
           "local_cache_hits_in_log": len(hits), "rows_total": len(rows), "rows_measured": len(real)}
    (ROOT / "evidence" / "tokenomics.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
