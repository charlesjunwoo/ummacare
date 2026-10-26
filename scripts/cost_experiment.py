"""Did our main cost cut (reasoning effort 'low') hurt quality? Runs the same two workflows with effort
'low' (shipped) and 'medium' on identical inputs, 2 trials each, and records measured usage plus simple quality
checks:
  * key moments: number of validator retries, moment count, whether a 'gluten' practical claim is found
  * connections on the demo lecture: whether the known conflict (speaker's gluten claim vs. Dr. Kim note) is found,
    and whether every cited id was valid on the first try (requests == 1)
Writes evidence/cost_experiment.json. Uses the evidence-run database (read-only use of its records).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("UMMACARE_DATA_DIR", str(ROOT / "backend" / "data" / "runtime"))

from pydantic_ai.models.openai import OpenAIResponsesModelSettings  # noqa: E402

from app import ai, db, pipeline, records  # noqa: E402
from app.agent import ConnectDeps, TranscriptDeps, connect_agent, moment_agent  # noqa: E402
from app.youtube import fmt_time  # noqa: E402


def settings(effort: str):
    return OpenAIResponsesModelSettings(openai_reasoning_effort=effort, max_tokens=6000, openai_store=False)


async def run_once(agent, prompt, deps, effort):
    t = time.perf_counter()
    r = await agent.run(prompt, deps=deps, model=ai.model(), usage_limits=ai.limits(), model_settings=settings(effort))
    u = r.usage() if callable(r.usage) else r.usage
    usage = dict(requests=u.requests, input=u.input_tokens, cached=u.cache_read_tokens, output=u.output_tokens,
                 reasoning=getattr(u, "output_reasoning_tokens", 0) or 0, latency_s=round(time.perf_counter() - t, 2),
                 cost_usd=round(ai.cost_usd(u.input_tokens, u.cache_read_tokens, u.output_tokens), 6))
    return r.output, usage


async def main():
    out = {"note": "Measured with the real model; 2 trials per setting. 'low' is what UmmaCare ships.", "trials": []}
    demo = db.row("SELECT id FROM videos WHERE title LIKE 'Understanding Fatigue%'")["id"]
    text, n, _ = pipeline.transcript_for_prompt(demo)
    m_prompt = "Video title (metadata only, not evidence): Understanding Fatigue\n" + ai.wrap_untrusted("transcript", text)

    # rebuild the exact connection prompt the pipeline used for the demo lecture
    ms = db.rows("SELECT * FROM moments WHERE video_id=? ORDER BY position", (demo,))
    own = {("moment", m["id"]) for m in ms}
    cands, refs, lines, items = {}, {}, [], set()
    for i, m in enumerate(ms, 1):
        claims, topics = json.loads(m["claims"]), json.loads(m["topics"])
        for h in db.search_records(f"{m['heading']} {' '.join(topics)} {' '.join(claims)}", limit=5, exclude=own):
            d = records.describe(h["kind"], int(h["ref_id"]))
            if d:
                cands[f"{d['kind']}:{d['id']}"] = d
        for r in db.search_references(" ".join(claims + topics) or m["heading"], limit=2):
            refs[r["id"]] = r
        lines.append({"id": f"M{i}", "heading": m["heading"], "timestamp": fmt_time(m["start"]), "speaker_says": m["explanation"],
                      "claims": claims, "excerpt": m["excerpt"][:700]})
        items.add(f"M{i}")
    c_prompt = ("NEW MATERIAL — key moments from a video she just added:\n" + ai.wrap_untrusted("video_moments", json.dumps(lines, ensure_ascii=False, indent=0))
                + "\n\nCANDIDATE EARLIER RECORDS (from keyword search; may be irrelevant):\n" + pipeline._candidate_block(cands)
                + "\n\nREFERENCE PASSAGES:\n" + pipeline._ref_block(refs))
    kim = next(k for k, d in cands.items() if d["title"].startswith("Dr. Kim"))

    for effort in ("low", "medium"):
        for trial in (1, 2):
            mo, mu = await run_once(moment_agent, m_prompt, TranscriptDeps(n_segments=n), effort)
            gluten = any("gluten" in (x.heading + " ".join(x.claims)).lower() for x in mo.moments)
            co, cu = await run_once(connect_agent, c_prompt, ConnectDeps(items, set(cands), set(refs)), effort)
            conflict = any(c.relation == "conflicts" and c.record_ref == kim for c in co.connections)
            out["trials"].append({"effort": effort, "trial": trial,
                                  "moments": {**mu, "n_moments": len(mo.moments), "found_gluten_claim": gluten},
                                  "connections": {**cu, "n_connections": len(co.connections), "found_known_conflict": conflict,
                                                  "valid_first_try": cu["requests"] == 1}})
            print(effort, trial, out["trials"][-1], flush=True)
    (ROOT / "evidence" / "cost_experiment.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    db.init()
    asyncio.run(main())
