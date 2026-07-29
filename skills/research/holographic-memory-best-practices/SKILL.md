---
name: holographic-memory-best-practices
description: >-
  Use when writing facts to the holographic memory store — quoting discipline,
  pre-write checkpointing, trajectory updates, contradiction gates, and SNR
  management. Also for deep maintenance, complex corrections, and full write
  procedures. The 4-rule floor lives in SOUL.md.

version: 4.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [memory, fact-store, holographic, conventions, agent-discipline]
    related_skills: [holographic-memory-janitor, holographic-memory-reflect]

---

# Holographic Memory: Agent-Facing Discipline

## Overview

Authoritative, unified holographic memory discipline reference. The 4-rule floor lives in `SOUL.md` (`# Holographic Memory Discipline`), always active. This skill covers routine writes (pre-write checkpoint), complex corrections, janitor deep-cleaning, and full procedures. Principles: write to evidence not intuition · trajectory over addition (update, don't duplicate) · SNR preservation (one slot, one vector).

**When to use:** before any `fact_store` add/update, when the user asks to remember/save/update knowledge, in janitor/reflect sessions, or for full procedures.

## The One-Line Rule

Tags = domain/scope. Content = atomic. Entity = anything the regex extracts (quoted terms, multi-word Capitalized Phrases, AKA). Category is load-bearing — distribute across all four for O(1) category-scoped retrieval and to avoid exceeding per-bank SNR capacity (≈ hrr_dim/4 facts per category — e.g. ~256 at the 1024-dim default, ~1024 at 4096-dim).

---

∎ THREE UNBREAKABLE RULES ∎

1. **Run `contradict()` before adding a fact asserting state about a SHARED entity.** Skip only for genuinely new entities with no prior facts.
2. **Every important entity goes in double quotes, especially single‑word names.** Unquoted single words (any case) are invisible to extraction.
3. **Distinguish encoding fixes from content changes.** `update` replaces the vector in-place for link/quote/tag fixes; `remove`+`add` only when the real-world fact changed and the old one is obsolete.

---

## Core Taxonomy & Tag Management

Use a stable lower-case kebab-case set (e.g. `home-infra`, `networking`, `work`, `coding`, `health`, `finance`, `media`, `mobility`, `learning`, `preferences`). Plural nouns for categories; never combine unrelated domains in one fact. **Search before minting:** `fact_store(action='search', query='<domain>')` — create a tag only if none covers it.

## Category Enum Lockdown

`category` is a strict enum of four: `user_pref`, `project`, `tool`, `general`. Any other string is schema-rejected on `add`. Distribute accurately — each bank is SNR-limited to ~hrr_dim/4 facts (capacity scales with dimension: ~256 at 1024-dim default, ~1024 at 4096-dim); defaulting to `general` wastes three banks and caps the store at one quarter of its potential. The O(1) fast path and SNR capacity are architecturally real. An approximate category beats `general`.

## Entity Quoting: The Minimal Quoting Rule

Regex catches multi-word capitalized phrases (`Home Network`, `John Doe`) automatically — **do NOT quote them**. It catches `"double-quoted"` terms only when quoted. `_RE_CAPITALIZED = \b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b` matches multi-word title-case only; FTS5 strips quotes from indexed content, so quotes add no retrieval benefit for phrases — a write-time bind signal.

| Entity type | Example | Quote? | Why |
|---|---|---|---|
| Multi-word capitalized phrase | `Home Network`, `Metro City Tower` | **No** | Auto-extracted by `_RE_CAPITALIZED` |
| Capitalized single-word | `Python`, `Linux`, `CityX`, `ConditionA`, `MedicationB`, `InsurerC`, `CountryY`, `User` | **MANDATORY** | Single words are NEVER auto-extracted — invisible unless double-quoted |
| Non-capitalized single-word | `kubernetes`, `prometheus`, `vault`, `Homebrew` | **Yes** | Regex requires `[A-Z]` |

ALL CAPS acronyms (`ConditionA`, `InsurerC`, `MedicationB`, `LTVP`, `GCP`) are single-word and MUST be quoted. Compound entities: quote only the unique name (`Office "OfficeTower" floor 12`). AKA: `content='"home-infra" aka "home network" refers to the local network'` binds both. **FTS5 dual-column trap:** `facts_fts` is `fts5(content, tags, content=facts)`; `MATCH 'ConditionA'` hits both columns — use `content:ConditionA`. See `references/fts5-dual-column-trap.md`.

## Atomicity & Cohesion

**Atomicity:** one fact, one claim. Self-test: *"If false, would exactly one piece of knowledge be affected?"* Split lists/multi-attribute/multi-claim facts. Operational separability, not the word "and", is the test — inseparable clauses stay together. Bundled facts break `reason()`, trust scoring, and independent retrieval.

**Cohesion Test (reverse):** *"If separate, would any lose meaning alone?"* If yes, bundle as one fact. Combined rule: multiple independent claims → split; separating loses meaning → bundle.

## Stability Litmus Test

Add only declared-stable choices ("I always use…", "my setup is…", confirmed repeated patterns, persistent configs). **Never add** transient state ("trying X this week", "just installed Z", "what I did today"). Transient facts pollute the store and dilute trust.

## Content Writing Rules

Declarative not instructional (`"User prefers dark mode"` not `"Always use dark mode"`); be specific; put detail in content (FTS5/Jaccard search it); natural self-contained language (no "see above"); synthesize history when correcting.

## Contradiction Gate (Resolved Policy)

The system does **not** block contradictory adds — you enforce it. **One policy:** run `contradict()` before adding a fact that **asserts state about a SHARED entity**; skip for genuinely new entities with no prior facts. The trigger is a shared entity with possible prior state — nothing narrower.

```python
fact_store(action='contradict', category='<target-category>')
```
Returns only pairs ≥0.3 threshold. Takes **no `query`**, **silently ignores `entity`** (scans whole category, optionally filtered). Failure modes: `entity=` ignored (filter by `shared_entities`); numpy absent → `[]` silently (empty ≠ none); **capped at 500 facts** (older facts invisible — cover with `reason()`). If it returns a pair: pause, show both + `contradiction_score`, resolve, then add.

## Updating Facts (Correct Semantics)

`fact_feedback` is standalone — NOT `fact_store(action='fact_feedback')`. `fact_store(action='update')` calls `update_fact`, an **in-place UPDATE** (NOT `remove`+`add` internally).

`update_fact` behavior (plugin truth):
- **`content=None`** → metadata-only (`tags`/`category`/`trust_delta`); recompute **skipped**; `trust_score`, `helpful_count`, entity links preserved.
- **`content` provided** → HRR vector **recomputed and entities re-extracted unconditionally**; there is **no byte-equality skip** — verbatim content still re-extracts. To change bindings, **change the quotes**, not the bytes.
- `updated_at` always refreshed → resets temporal-decay timer.

Patterns: **A** metadata-only `update` (preserves trust); **B** `feedback unhelpful`+`add` for deprecated-but-referenced; **C** `remove`+`add` for wholly obsolete; **D** `update` Trajectory Format `[Current] (previously [Old] | Origin: [Initial])` for real-world evolution (one slot, trust kept). UNIQUE trap: `add` with identical content silently returns the existing id — use `update` for metadata changes.

## Garbage Collection

`min_trust_threshold` (0.3) hides low-trust facts but never deletes them. When an old fact is replaced/false/has no reference value: `remove` then `add` with synthesized history. Use feedback-only deprecation when still queryable.

## Trust Scoring & Temporal Decay

New facts = 0.5. `helpful` → +0.05 (helpful_count+1); `unhelpful` → −0.10; clamped [0,1]; `final_score = relevance × trust`. No `unhelpful_count` column. Asymmetry: three unhelpful votes from 0.5 (0.40→0.30→0.20) hide a fact. **Temporal decay** (`relevance × trust × 0.5^(age/half_life)`) is **disabled by default** (`temporal_decay_half_life = 0`) — facts don't expire unless configured; if enabled, refresh stable facts via `update(fact_id=N, content=None)`. Decay is independent of trust, reset only by `update` (not `feedback`).

## Fact Store vs Memory Tool

`memory_tool` (`add`, `target='user'`): always-on identity/preferences, never mid-session retrieved; auto-mirrored to `fact_store` as `user_pref` (reverse never happens). `fact_store`: everything queryable — prefer it if unsure.

## Temporal Encoding Discipline

Embed dates as ISO 8601 (`2025-09-30`) in the content string. The janitor parses `\b\d{4}-\d{2}-\d{2}\b` to detect temporal sequences. Do NOT store dates as separate metadata — the plugin has no temporal fields; dates live in content as strings. Cross-check the conversation-header date against the user's stated context; never treat the header as authoritative once the user corrects it.

## Storage Tier Discipline

| Content type | Lives in | Why |
|---|---|---|
| Procedural / how-to | Skills | Auto-loaded on trigger; survives model changes |
| Facts / preferences / who-the-user-is | `fact_store` | Queryable, HRR-indexed, cascaded |
| Compiled knowledge / chains / narrative | llm-wiki [optional] | Pre-composed reasoning; user-readable (if installed) |
| Operational rules (always-on) | `memory` (short context) | Pre-injected every turn |

Default order: skill → fact_store → wiki [if configured] → memory (last resort). If `memory` exceeds 80% capacity, consolidate proactively. See `references/memory-skill-boundary.md` for the memory-vs-skill discipline this extends.

## Probe Before Answering

`probe(entity='"home-infra"')` (quoted → HRR). `probe('home-infra')` unquoted falls back to FTS5 only when numpy is absent; with numpy it returns confident noise on unbound entities. For any single-word entity prefer `search()`. `reason(entities=[A,B])` requires both bound in the SAME fact.

## When to Add / Not Add

Add on correction, stable preference/life context, stable environment fact, confirmed convention, or identified stable future-relevant item. **Do NOT add** raw task output, transient session state, progress, or experiments.

## The `list` Tool

`list` returns only the most recent facts (small `limit`); **no `offset`, no `tags` filter**. Use `search` for inventory.

## Common Pitfalls

1. **Bundling unrelated entities/claims** — split atomically.
2. **Tags to bundle** — split independent claims.
3. **Storing task/session state** — keep transient out.
4. **Not rating after use** — trust doesn't self-improve.
5. **Defaulting to `general`** — wastes three banks, caps SNR at ~hrr_dim/4 per bank.
6. **Fighting the entity regex** — quote single words; FTS5 for lowercase.
7. **Relying on `list` for inventory** — top-N only; use `search`.
8. **Confusing append-only with `update`** — `update` is in-place, preserves trust; `feedback`+`add` pollutes SNR. Use `update` for encoding fixes.
9. **Skipping the gate on shared entities** — run `contradict()` before asserting shared-entity state; skip only for new entities.
10. **Transient preferences** — wait for stability.
11. **Minting tags blindly** — search first.
12. **Leaving obsolete facts** — `remove` when no reference value.
13. **`query`/`offset`/`entity` on unsupported tools** — `contradict` takes only `category`; `list` no pagination; `entity=` ignored.
14. **Splitting cohesive frameworks** — keep together if parts would be misleading alone (Cohesion Test).
15. **Empty `contradict` ≠ no contradictions** — may be numpy absent.
16. **`contradict` blind spot >500 facts** — older facts invisible; cover with `reason()`.
17. **False atomicity — splitting on "and" while still bundling** — each fact must be independently retrievable/trust-scored/useful.
18. **`add` to update metadata** — UNIQUE silent failure; use `update`.
19. **Assuming `probe` falls back for unquoted** — only when numpy absent; else noise. Use `search`.
20. **`update` recompute** — `content=None` skips; content provided re-extracts (no byte-equality skip); change quotes to change bindings. `update` is the correct repair tool.
21. **Hardcoding paths** — use `$HERMES_HOME` (`~` is OS home, not the profile).
22. **Invalid category silently accepted** — `financial`/`health` break the fast path; migrate + delete orphan `memory_banks` row.
23. **Wrong-dimension `hrr_vector` poisons bank** — 1024-dim in 4096-dim category fails every probe/reason; detect via `length(hrr_vector)` group-by, repair per-fact `update`.
24. **Gateway restart forbidden** — WAL lock held → tell user, never restart yourself.
25. **Stopping at empty search instead of cascading** — `search()` < 3 results → extract entities from the query, `probe(entity)` each (HRR-bound facts FTS5 may miss), `skill_view()` top-matching skills, and only then ask the user. `probe()` is algebraic, not keyword-based; clarification is the last resort.
26. **Guessing instead of checking system state** — one correction cycle costs more than one verification call. Current time → `date`; fact existence → `search`/`probe` first; location/status → ask or infer from explicit statements. If the sentence contains "probably"/"likely"/"I assume" or a time without a source, stop and check.
27. **`memory` at 99% blocks new writes** — `memory(action='add')` failing with "would exceed limit" forces a delete decision at the worst moment. Check `memory.usage` periodically; consolidate proactively at 95% (merge overlapping, drop redundant). When blocked mid-session, replace immediately while context is fresh.
28. **Substring matching for entity-link verification** — `.lower() in content.lower()` catches "EP" in "Keeping", "Shopping", "reksadana". Use word-boundary regex: `re.search(r'\b' + re.escape(word) + r'\b', content)`.
29. **Blind trust of the conversation-header date** — the header ("Conversation started: ...") is set once at session start and stays stable, not current; trusting it caused total date loss (reasoned about May 6 when it was May 30). If the user states/implies a different date, surface the conflict and use their date as anchor.
30. **`fact_entities` correct ≠ HRR vector correct** — after a bulk SQL quote fix, links may look right while the vector is stale (computed at write time from pre-fix entities). Symptom: `search()` finds the fact but `probe`/`reason` miss it. Fix: `update(fact_id=N, content=<current content>)` re-extracts + recomputes; a null-HRR fact is invisible to reflect regardless of trust.
31. **Memory duplicating skills** — don't store facts a skill already owns (tool behavior, API URLs, cron IDs). Pre-write: "Is this already covered by a skill?" — if yes, skip. Protected: personal/confirmed-life facts and user preferences/hard constraints — memory owns "who the user is," skills own "how the system works." For insurance/health-policy facts the user's own understanding supersedes fact_store content — hold rather than demote when uncertain.
32. **Syntheses about user files are inferences, not facts** — a reflect/wiki synthesis referencing a user-owned file (e.g., a PDF) is a hypothesis until the user confirms; memory cannot OCR or inspect binaries at write time. Never propagate into a wiki/skill evidence chain without asking (wiki only if llm-wiki installed). On correction: `fact_feedback(unhelpful)` + `add` the corrected fact.

## Pre-Write Mandatory Checkpoint (Non-Negotiable)

Run before EVERY `add` and `update`. One-sentence scanner:

> "One claim? Single-word entities quoted? Compound entities as single strings? Category distributed (not defaulted to `general`)? Stable? CONTRADICT scanned (if shared entity)? Trajectory preserved if the fact already exists?"

**Trajectory check (updates):** SEARCH first — is this already stored? If YES → `update` with `[Current State] (previously [Old State])`. If NO → `add`. Never add a duplicate for the same conceptual entity — one slot, one vector, evolved in place.

**Checklist:**
1. **Atomic** — one claim, no "and" coupling?
2. **Quoted** — every single-word term double-quoted; multi-word title-case unquoted?
3. **Compound** — contiguous concept quoted as one string (`"Acme OfficeTower"`)?
4. **Category** — accurately distributed, not `general`?
5. **Tags** — comma-separated with space-after-comma?
6. **Stable** — confirmed long-term pattern, not transient?

## HRR Physics

`trust_score` is a retrieval filter, not a storage filter — `_rebuild_bank()` and `probe`/`reason`/`related` query `WHERE hrr_vector IS NOT NULL`, no trust clause; a trust=0.1 fact still consumes SNR. **Rule:** fact changed → `update` Trajectory; encoding wrong → plain `update`; zero reference value → `remove`+`add`; history matters AND distinct → `feedback`+`add`. See `references/hrr-architecture.md`, `references/hrsn-formulas.md`.

## Quick Reference

```python
# Add (after contradict() if shared entity)
fact_store(action='add', content='"home-internet" plan: 500 Mbps fiber',
    tags='home-infra, internet', category='general')
# Update in place (Trajectory) — SEARCH FIRST
fact_store(action='update', fact_id=42,
    content='"home-internet" plan: 1 Gbps fiber (previously 500 Mbps | Origin: 300 Mbps)')
fact_store(action='update', fact_id=42, tags='home-infra, networking')  # metadata-only
# Feedback is standalone (helpful +0.05 / unhelpful -0.10)
fact_feedback(action='helpful', fact_id=42)
fact_feedback(action='unhelpful', fact_id=42)
# Retrieve: search / probe(entity=quoted) / reason(entities=[...]) / list(limit=5)
```

## Supporting Files

`references/entity-extraction-gaps.md` · `references/hrr-architecture.md` · `references/hrsn-formulas.md` · `references/wal-locking-behavior.md` · `references/probe-failure-analysis.md` · `references/hrr-dimension-migration.md` · `references/fts5-dual-column-trap.md` · `references/recovery/bank-corruption-diagnosis.md`.

## Verification Checklist

**Pre-write:** one testable claim · single-word entities double-quoted (any case), multi-word title-case unquoted · compound entities quoted · category accurate (not `general`) · tags comma-separated · stability confirmed · `SEARCH` before `ADD` · `contradict()` run when asserting shared-entity state (skip only for new entities).
**Post-write:** retrievable via `probe`/`search` · no duplicate slots.
**Janitor:** per-category `contradict`; rate/remove stale; unlink orphans; fix tags. **Reflect:** `reason(entities=[...])`; synthesis at trust=0.3; retrievable in `probe`.

## Recovery: Bank Corruption

`np.array(...)` failing with `inhomogeneous shape` → see `references/recovery/bank-corruption-diagnosis.md`.

---

*Supplements the holographic memory plugin. Every rule verified against actual Hermes backend behaviour.*
