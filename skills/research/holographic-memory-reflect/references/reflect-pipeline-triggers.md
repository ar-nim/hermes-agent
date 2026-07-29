# Reflect Pipeline Triggers (Reference)

## When Reflect Runs

Reflect is a **cron-only** trigger. There is no post-write hook, no `needs-reflect` flag, no Tier 1 bookkeeping.

The pipeline runs on a schedule and reads the database state at that moment. If no cursor fact exists yet, the cron falls back to a 7-day window on its first real fire — but this is a **state-read** behavior, not a triggering mechanism.

## Reflect vs Janitor — Operational Distinction

| | Reflect | Janitor |
|---|---|---|
| **Trigger** | Cron only (daily @ 22:00 local time) | User command ("run the janitor") |
| **Output** | New synthesis facts | Fixes, deprecations, deletions |
| **Direction** | Memory → memory (generative) | User → memory (corrective) |
| **Metadata bookkeeping** | None — scan `created_at`/`updated_at` directly | None — same |

## First-Run Bootstrap

1. Create cursor file: `<skill_dir>/scripts/holographic_cursor.sh write "<7-days-ago>"`
2. Execute Steps 2–7 inline
3. Cron takes over next day

Do NOT rely on `cronjob run` to bootstrap — it fires the skill but output may not route back to the originating chat. The file cursor survives job deletion/recreation.

## fact_store API Pitfalls

**`trust_score` silently dropped on `add`:** The `fact_store(action='add')` API does not accept `trust_score`. The parameter is not in the schema, not read from args, and silently ignored. All facts are created at `self.default_trust` (store default, 0.5). There is no per-fact trust on creation.

**Workaround for synthesis trust floor:** After writing a synthesis fact, call `fact_feedback(action='unhelpful', fact_id=<new_fact_id>)` twice to push trust from 0.5 → ~0.3. The `unhelpful` delta is approximately -0.1 per call.

**`add` response is minimal:** The add response only returns `{"fact_id": N, "status": "added"}` — no `trust_score` or any other field. Trust only appears in `list`, `probe`, `search`, `reason`, and `contradict` responses.

## Contradiction Patterns

The most common contradictions in this store:

**Duplicate facts (same entity, different trust):** Occurs when the same fact was stored twice at different trust scores (e.g., fact_id 35 vs 78 for "Core leaders"). Resolution: deprecate the lower-trust duplicate via `fact_feedback(action='unhelpful', fact_id=<lower>)`. User-supplied facts always win — do NOT deprecate trust 0.5 facts.

**Same-content different-wording:** Two facts with identical meaning but different phrasing. Treat as duplicates.

## Synthesis Failure Handling

If the pipeline fails mid-run:
- Do NOT roll back — facts written before failure stay
- Write a `reflect-incomplete` flag fact noting where it stopped
- Next successful run should note the incomplete state
