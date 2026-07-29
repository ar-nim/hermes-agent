# Reflect Pipeline Architecture

## The Problem: Prose as Code

SKILL.md had pipeline logic embedded as prose code blocks. The cron agent interpreted the prose and executed it — but:
- No tests could run against prose (not Python)
- Logic could drift from description without detection
- "Deterministic" parts (staleness detection, entity classification) were mixed with LLM-dependent parts (synthesis) in the same prose blocks

## The Solution: Tested Module + Entry Point

```
SKILL.md                    ← authoritative prose spec (agent reads this for LLM steps)
reflect_pipeline.py         ← tested Python (deterministic functions)
  reflect_pipeline.py is NOT called by cron directly — see below

scripts/
  reflect_run.py            ← no_agent entry point for Step 0 (deterministic)
                              called by cron as script=

cron job <cron-id>:
  skill: holographic-memory-reflect
  script: reflect_run.py    ← Step 0 runs as no_agent script
  no_agent: true
  Steps 1-7 (LLM synthesis): TBD — currently still LLM-driven via skill
```

## Why Step 0 Is No-Agent

Step 0 (stale synthesis detection + in-place refresh) is fully deterministic:
- SQL query: `SELECT WHERE status:current AND type:synthesis`
- Compare timestamps: `component.updated_at > synthesis.created_at`
- In-place UPDATE with history append

No LLM needed. Runs reliably at 02:00 local time without token cost or latency.

## Why Steps 1-7 Are Still LLM-Driven

Synthesis, entity classification, and session reasoning require LLM:
- Generating higher-order inferred claims from fact patterns
- Deciding Path A (evolution) vs Path B (connection)
- Detecting contradictions and deciding disposition

These cannot be deterministic scripts. The agent handles them by reading SKILL.md.

## The TDD Split

| Component | Type | Tested? |
|---|---|---|
| `detect_staleness()` | deterministic | ✅ 5 tests |
| `classify_entity_temporal()` | deterministic | ✅ 5 tests |
| `compute_entity_stats()` | deterministic | ✅ 5 tests |
| `compute_window()` | deterministic | ✅ 4 tests |
| `refresh_synthesis()` | deterministic | ✅ 3 tests |
| `execute_step0()` | deterministic (calls above) | ✅ integration test |
| `deduplicate_sessions()` | deterministic | ✅ 3 tests |
| `plan_deep_session_calls()` | deterministic | ✅ 3 tests |
| LLM synthesis (Steps 4-7) | non-deterministic | ❌ cannot test |

Tests live in `tests/test_reflect_pipeline.py`. Run: `pytest tests/ -v`

## Key Design Decisions

1. **No external state file for Step 0** — `synthesis.created_at` is the idempotency key. Double-refresh produces same content, harmless.

2. **In-place refresh over new-fact** — preserves epistemological chain. History lives in content, not as separate facts (which would accumulate and pollute HRR bank).

3. **No concurrent-protection lock file** — in-place UPDATE is idempotent. If cron overlaps (manual trigger during cron run), second run sees same timestamps and produces same result.

4. **`reflect_pipeline.py` path resolution** — HERMES_HOME env var is set by Hermes runtime. Use it directly, not `os.path.expanduser("~/.hermes")` which would double-expand.

5. **DB path** — `memory_store.db` at HERMES_HOME root, not `memory/memory_store.db` (that subdirectory doesn't exist).

## Current Cron Configuration

```python
cronjob(action="update", job_id="<cron-id>",
    name="holographic-memory-reflect",
    skill="holographic-memory-reflect",
    script="reflect_run.py",
    no_agent=True,
    schedule="0 2 * * *",  # 02:00 local time daily
    deliver="telegram:CHAT_ID",
)
```

## Pending: Steps 1-7 as no_agent

Still LLM-driven. The long-term goal would be to have a script that calls `reflect_pipeline.py` for Steps 0-3 (deterministic) and uses LLM only for Steps 4-7 — but this requires restructuring how the cron invokes the agent.