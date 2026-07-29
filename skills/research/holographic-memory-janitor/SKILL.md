---
name: holographic-memory-janitor
description: >-
  Use when running interactive maintenance on the holographic memory store —
  cleanup, audit, deduplication, integrity checks, or the 4-way reranking
  audit (fact verification against session history, skills, optional wiki,
  and fact_store self-consistency). Corrective and reactive. For autonomous
  synthesis, use holographic-memory-reflect instead.
version: 2.8.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [memory, fact-store, holographic, maintenance, janitor, reranking, audit]
    related_skills: [holographic-memory-best-practices, holographic-memory-reflect]
---

# Holographic Memory Janitor: Interactive Maintenance

## Overview

The janitor is the **corrective maintenance layer** for the holographic fact store. It is interactive and reactive — it fixes problems flagged by the user or by automated trigger checks (e.g., entity binding rates below threshold). It asks before every action and produces an end-of-session summary of what was done.

Unlike the reflect skill (generative, autonomous, cron-triggered), the janitor is directed by the user and operates on existing facts. Both are operationally distinct — they cannot be merged.

## When to Use

- User says "run the janitor" or "run holographic memory maintenance"
- Entity binding audit reports entities below healthy threshold
- User asks to clean up, audit, or review the holographic memory store
- After a data-corruption incident or bad reflect run
- User says "reranking audit" or "audit memory" → run Pass 8 (4-Way Reranking Audit)
- After major life events (EmploymentTransition, marriage, relocation) that stale entire fact clusters → Pass 8
- When fact trust scores feel disconnected from reality → Pass 8

**Don't use for:** single-fact corrections (use `fact_store update` directly), first-time fact entry (`holographic-memory-best-practices`), or synthesis generation (`holographic-memory-reflect`).

## Core Design Principles

**1. SIR > SNR for definition quality.** SNR measures vector capacity. SIR (Signal-to-Interference Ratio) measures whether the tokens in a definition fact pull in the same direction. A high-SNR bank can still have zero useful retrieval if tokens are not discriminative. Audit definitions by SIR, not raw SNR.

**2. Vanilla definitions encode ontology; contextualized definitions encode state.** Definitions (what an entity IS) and state facts (application status, blockers, current context) must be separate facts. Mixing them creates temporal entanglement.

**3. Trust is a retrieval-layer parameter, not an encoding parameter.** Trust does NOT affect HRR phase encoding or binding arithmetic. It operates exclusively at ranking. A new fact at trust 0.8 does not "protect" its vector — it only inflates retrieval rank. The honest starting point for any unverified fact is trust 0.5. (Verified model: single tier, default 0.5; `helpful` +0.05, `unhelpful` -0.10, clamped [0,1]; `score = relevance × trust`.)

**4. Ontology and epistemology must stay separate.** Definition facts = what an entity IS. State facts = what the system knows NOW. Do not mix them in a single fact.

**5. Not fighting the system.** Every decision should improve entity binding, reduce phase smear, and support algebraic retrieval. The system's architecture is ground truth.

**6. Skill is authoritative over code during sessions.** If source code appears to contradict the skill, note the discrepancy, complete the scheduled passes as written, and report the code discrepancy separately after the session. Never patch the skill mid-session based on code findings.

**7. Trust scores are retrieval priorities, not truth values.** A high-trust falsehood is worse than a low-trust uncertainty. Always verify content after adjusting scores.

## Profile-Aware Execution (Two-Layer Defense)

When this skill accesses `memory_store.db` directly (SQLite fallback), verify the correct profile context.

**Layer 1 — Read the active profile:**
```python
import os
active_file = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/active_profile"
if os.path.exists(active_file):
    profile = open(active_file).read().strip()
else:
    profile = "default"
```
If `profile` is empty or `"default"`, use `"default"`.

**Layer 2 — Verify the profile directory exists:**
```python
hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
profile_dir = os.path.join(hermes_home, "profiles", profile)
if not os.path.isdir(profile_dir):
    raise RuntimeError(f"Profile '{profile}' listed in active_profile but no directory found at {profile_dir}. Aborting for safety.")
```
**Critical:** Never silently fall back to `"default"` when the profile directory is missing. Raising an error forces explicit resolution rather than corrupting the wrong store.

**Profile blocklist (never auto-activate janitor for these):** `{"work-profile"}` — running janitor on it from a bot profile operates on the wrong data.

---

## Pre-Flight: DB Health

Before any pass, verify the database is accessible and structurally sound.

**1. WAL safety.** The MemoryStore shared connection (`store.py:98-112`) eliminates cross-connection WAL contention. Verify connectivity:
```bash
python3 -c "
from store import MemoryStore
store = MemoryStore()
print('READ OK,', store._conn.execute('SELECT COUNT(*) FROM facts').fetchone()[0], 'facts')
store.close()
"
```
If the read fails with `database is locked` → gateway restart race → tell the user, wait. **⚠️ NEVER restart the gateway yourself.**

**2. Schema verification.**
```python
from store import MemoryStore
store = MemoryStore()
rows = store._conn.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for r in rows: print(r[0])
store.close()
```
Verify: `content TEXT NOT NULL UNIQUE`, tables (`facts`, `entities`, `fact_entities`, `facts_fts`, `memory_banks`), FTS triggers.

**3. Load best-practices.**
```bash
skill_view(name='holographic-memory-best-practices')
```

## Pre-Flight: Entity Health

**1. HRR vector integrity** — run `check_hrr_health.py` to detect inhomogeneous byte-length vectors (bank corruption) and NULL vectors (invisible to HRR). If corruption detected → stop and run Pass 0.

**2. Entity binding rates** — run `check_entity_bindings.py` to identify store-derived entities with poor binding rates (bound/fts_mentions < 0.85). If entities flagged → Pass 1 investigates.

**3. Category size check** — per-category counts. Above 500 facts the contradiction gate is unreliable; keep below 300. See `references/audit-procedures.md` § Category Size Escalation Protocol.

---

## DB Access Rules

- **MemoryStore shared connection** — the holographic memory plugin (store.py:98-112) uses a process-wide shared connection pool. All MemoryStore instances share ONE connection with a re-entrant lock, eliminating cross-connection WAL contention.
- **All writes** → fact_store tool (uses gateway's own connection, available in interactive sessions).
- **Simple reads (probe, search)** → fact_store tool.
- **Cron environment reads** → terminal with sqlite3 CLI or a MemoryStore script (preferred).
- **WAL safety:** the shared connection eliminates cross-process WAL contention. Never restart the gateway yourself.
- **Two-phase fix for entity quoting:** Phase 1 (bulk quoting via SQL) computes new quoted content strings; Phase 2 (`fact_store update` per fact) is mandatory — it triggers `_extract_entities()` AND `_compute_hrr_vector()`. Never skip Phase 2.
- **Exception — Pass 1 discovery only:** the entity density JOIN query has no built-in tool equivalent; `execute_code` is acceptable strictly for discovery, not fixes.

---

## The Janitor Loop

For each category, execute passes in order. Complete one pass before starting the next. **Pass 0 runs only if the HRR health pre-flight flagged corruption.** Skip it on a clean store. **Pass 8 (4-Way Reranking Audit) is store-wide** — run it as the closing pass, or standalone when the user asks for a "reranking audit".

### Pass 0: Bank Integrity Repair

**Problem:** a fact has `hrr_vector` at a different dimensionality (in bytes / 8) than the rest of the bank. When `_rebuild_bank()` bundles vectors, numpy rejects the inhomogeneous list; every subsequent `add` / `update` / `probe` in that category fails with `setting an array element with a sequence. The requested array has an inhomogeneous shape after 1 dimensions.`

**Procedure — the "last update succeeds" pattern:**
`update_fact()` runs in this order: (1) `UPDATE facts SET content=...`; (2) re-extract + re-link entities if `content is not None`; (3) `_compute_hrr_vector()` — **commits a fresh vector at the correct dim BEFORE the bank rebuild**; (4) `_rebuild_bank()` — **may FAIL while any sibling vector is still wrong-dim**. So even when `update` returns the rebuild error, the targeted fact's vector is already recomputed at the correct dim. Only the FINAL update (removing the last outlier) returns `{"updated": true}`. The first N-1 errors are expected and non-fatal.

For each corrupt fact returned by `check_hrr_health.py`:
```bash
fact_store(action='update', fact_id=<N>, content=<verbatim current content>)
```

**Do not pre-emptively modify the content.** `update_fact` has no byte-equality check (guard is `if content is not None`); passing the verbatim current string DOES trigger recompute.

**Completion criteria:**
```bash
python3 scripts/check_hrr_health.py   # → "All vectors homogeneous and non-null."
```
**Prevention:** the reflect pipeline must read `hrr_dim` from `config.yaml` before instantiating `MemoryStore()`. See `references/bank-corruption-diagnosis.md` for the full RCA.

### Pass 1: Entity Extraction & Binding Audit

**Purpose:** Identify entities with poor binding rates and facts with zero entity bindings. Both reduce HRR retrieval quality — unquoted entities get zero binding, making facts invisible to `probe()` / `reason()`.

**Diagnosis:** run `check_entity_bindings.py` to identify store-derived entities with low binding rates. Also scan for zero-entity facts:
```python
import sqlite3, os
conn = sqlite3.connect(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')) + '/memory_store.db')
conn.row_factory = sqlite3.Row
for cat in ('user_pref', 'general', 'tool', 'project'):
    rows = conn.execute("""SELECT f.fact_id, f.content FROM facts f
        LEFT JOIN fact_entities fe ON fe.fact_id = f.fact_id
        WHERE f.category=? AND f.hrr_vector IS NOT NULL AND fe.fact_id IS NULL
        ORDER BY f.fact_id""", (cat,)).fetchall()
    print(f"{cat}: {len(rows)} zero-entity facts")
```

**Problem:** Unquoted entities are never extracted by `_extract_entities()` — they get zero HRR binding. Every fact containing an important entity must quote it in its content. Single-word capitalized / ALL CAPS terms (`User`, `ConditionA`, `MedicationB`, `InsurerC`, `LocalTZ`) are NOT auto-extracted by `_RE_CAPITALIZED` (requires 2+ title-case words) — they must be explicitly double-quoted.

**Word-boundary rule:** use `(?<!\")\bentity\b(?!")` — don't match already-quoted entities, don't treat substrings as matches.

**Empirical finding:** content containing an entity name does NOT mean it is bound in `fact_entities`. Always verify binding via direct SQL JOIN, never infer from content.

**Fix:** For each unbound fact, add double quotes around the most important entity. `fact_store update` with quoted content triggers `_extract_entities()` → `_resolve_entity()` → `_link_fact_entity()` → `_compute_hrr_vector()`. Batch 5-10 per tool call. Verify bindings via `fact_entities` SQL after each batch.

**Critical (verified):** `update_fact` recomputes on ANY `content` argument — the guard is `if content is not None`, NOT byte-equality. Passing byte-identical unquoted content returns `{"updated": true}` but yields no new bindings (the recompute ran, found nothing new). To add bindings you must **ADD THE QUOTES**.

**Completion criteria:** Pass 1 fixes verified via `probe()` and `fact_entities` SQL JOIN; binding rates at or above threshold.

### Pass 2: Bundled Facts (Atomicity Violations)

**Problem:** Multiple independent claims stored as one fact pollute HRR retrieval — a query for A returns B's noise.

**Detection:** `§` separator = always bundled. Also scan long (300+ char) multi-claim facts.

**Tight-coupling principle — DO atomize (format-bundled):** `§`-separated sections, multi-session captures of the same event, P0 incident duplicates, kitchen-sink mega-bundles (10+ unrelated life domains), one-liner summaries fully superseded by a detailed sibling.

**DO NOT atomize (conceptual bundles):** identity snapshots (job, income, family health, travel, medication organically coupled), medical management protocols, system configuration facts, user preference clusters forming a coherent philosophy, user-confirmed coupled claims. The user is the authority.

**MANDATORY: show raw content before asking.** Present the exact content and entities via SQL; never pre-filter or summarize. The user decides conceptual-coupling vs format-bundling.

**Pre-check before any `fact_store update`:** if two facts share the same content string, the later update fails with `UNIQUE constraint failed`. Differentiate (append a parenthetical) before updating.

**Fix:** present raw content, ask split / keep / specify.

**Completion criteria:** user decisions recorded; all genuinely-new components secured as standalone atoms before the bundle is deprecated.

### Pass 3: Cohesion Violations

**Problem:** Related claims scattered across multiple facts that should travel together.

**Procedure:** Present raw content (not tables — tables strip context) for each candidate and let the user decide merge / keep separate / deprecate. Verify bundle components against the store via `probe()` / `search()` before presenting a demotion.

**FTS drift check:**
```python
import sqlite3, os
conn = sqlite3.connect(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/memory_store.db")
conn.execute('PRAGMA query_only=ON')
total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
total_fts = conn.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
drift = total_fts - total_facts
orphaned = conn.execute("SELECT COUNT(*) FROM facts_fts fts LEFT JOIN facts f ON fts.rowid=f.fact_id WHERE f.fact_id IS NULL").fetchone()[0]
missing = conn.execute("SELECT COUNT(*) FROM facts f LEFT JOIN facts_fts fts ON f.fact_id=fts.rowid WHERE fts.rowid IS NULL").fetchone()[0]
print(f"Drift: {drift}, Orphaned FTS: {orphaned}, Missing FTS: {missing}")
```
**Acceptable state:** drift = 0, orphaned = 0, missing = 0. If drift found, report to user; FTS rebuild requires gateway restart.

**Completion criteria:** cohesion candidates resolved per user; FTS drift = 0.

### Pass 4: Tombstone Audit

**Problem:** Facts with trust at or below the retrieval floor (~0.3) are invisible to search but still occupy vector slots.

**Passive holding-area rule:** Tombstones are NOT a maintenance queue. Only act with a concrete reason: a clear higher-trust duplicate, a confirmed harmful factual error, or a merge opportunity. Do NOT systematically "clean" the 0.3 tier.

**Hard-delete-first rule:** prefer `fact_store remove` (reclaims the full vector slot). Deprecate (`fact_feedback unhelpful`) only when the old fact has specific historical query value. Pre-compute the target trust before mass deprecation: each `unhelpful` subtracts 0.10; better, use `fact_store update(fact_id, trust_delta=-X)` to set the target directly.

**Fix:** ask the user per candidate (DELETE / LEAVE AS-IS).

**Completion criteria:** candidates resolved per user; no systematic 0.3-tier sweep.

### Pass 5: Temporal Consistency Audit

**Purpose:** Detect outdated facts, flag superseded sequences, propose trajectory updates. The plugin has no built-in temporal reasoning; this pass scans content strings for ISO 8601 dates.

**Procedure:**
1. Scan content for `\b\d{4}-\d{2}-\d{2}\b`.
2. Group facts by shared entity (via `fact_entities` / `probe()`).
3. For each entity with ≥2 dated facts, sort by embedded date.
4. Flag sequences where a newer fact contradicts an older one without trajectory format.
5. Propose update with Trajectory Format: `"[New state] (previously: [old state])"`.

**Issue format:**
```
[JANITOR] #<fact_id> — temporal sequence detected
Entity: "<name>"
Older: #<old_id> — "<old content with date>"
Newer: #<new_id> — "<new content with date>"
Suggestion: Update newer fact with Trajectory Format
Action needed: YES to apply / NO to skip
```

**Completion criteria:** temporal sequences flagged for human judgment; user applies trajectory format where approved.

### Pass 6: Coreference Binding Proposal

**Purpose:** Detect potential unbound aliases and propose binding facts using the correct `X aka Y` format (`X also known as Y` also matches; "Entity X has aliases: Y" produces zero extraction).

**Procedure:**
1. Query `fact_entities` for all entity names.
2. For each, search facts for possessive patterns (`my <entity>`, `his <name>`, `the <descriptor> <name>`).
3. Propose binding for capitalized names near possessive pronouns.
4. Check aka patterns bound in only one direction.

**⚠️ SQLite REGEXP is NOT available — use Python `re`.** Any `WHERE content REGEXP ?` crashes with `no such function: REGEXP`. Fetch rows into Python, apply `re.search()`.

**RULE: Never auto-create bindings. Always ask.**

**Completion criteria:** proposed bindings confirmed by the user before any write.

### Pass 7: Neglect Detection (retrieval_count Awareness)

**Purpose:** Identify facts never retrieved (`retrieval_count` increments on search/probe/related/reason — observability ONLY, never scoring/ranking). These facts may need HRR recompute, entity re-quoting, or pruning.

**Prerequisite:** `retrieval_count` must be incrementing (confirm via `SELECT MAX(retrieval_count) FROM facts` > 0). If zero on all facts, the fix may not be deployed — skip this pass.

**Procedure:**
```bash
sqlite3 $HERMES_HOME/memory_store.db "SELECT fact_id, category, trust_score, retrieval_count, length(content), substr(content,1,80) AS preview FROM facts WHERE retrieval_count=0 ORDER BY created_at ASC LIMIT 20;"
```
For each zero-retrieval fact, diagnose: entity not quoted? (recommend `fact_store update` with quotes); content too generic? (split/rephrase); wrong category?; truly irrelevant? (`fact_feedback unhelpful` or remove). Also check high-trust zero-retrieval facts (may be over-trusted).

**What NOT to do:** do NOT bulk-remove zero-retrieval facts (binding may be broken, not content); do NOT auto-adjust trust (present to user).

**Interpretation:**
- `retrieval_count = 0` after 30+ days → genuinely neglected, review content.
- `retrieval_count = 0` AND `trust_score >= 0.7` → over-trusted.
- `retrieval_count = 0` AND null HRR vector → needs `fact_store update`.
- `retrieval_count > 0` AND `trust_score < 0.3` → retrieved but not trusted, review accuracy.

**Completion criteria:** neglected facts diagnosed and presented; user decisions recorded.

### Pass 8: 4-Way Reranking Audit

**Purpose:** Systematic audit of facts against four independent sources for accuracy, staleness, and contradictions. Designed for periodic maintenance (monthly/quarterly) or triggered by major life events that stale entire fact clusters.

Full batch mechanics and validated workflow: `references/four-way-reranking-audit.md`.

**Sources (authority order):**
1. **Session history** — what the user explicitly said/confirmed (`session_search`)
2. **Skills** — ground-truth schedules, endpoints, cron IDs, protocols (`skill_view`)
3. **Optional external wiki (llm-wiki)** — if installed. Skip if no wiki is configured.
4. **Fact_store** — self-consistency via `contradict()` and `reason()`

**Method — for each candidate fact,** query ALL four sources and assign a signal:

| Signal | Meaning | Action |
|--------|---------|--------|
| ✅ Corroborated | multiple sources agree | `fact_feedback(action='helpful')` — promotes trust |
| ⚠️ Mixed/Silent/Sensitive | unclear or health-related | NO CHANGE — hold |
| 🔴 Contradicted | sources disagree | `fact_feedback(action='unhelpful')`; if content wrong, flag for update |
| 💀 Obsolete | no longer applies to current reality | `fact_store(action='remove')` — user-approved only |
| 🔄 Update | content changed | `fact_store(action='update')` with Trajectory Format |

**Candidate tiers:**
- **A. High trust (≥0.55):** verify they're still correct
- **B. Synthesis facts (<0.40):** promote cross-domain gems to 0.35–0.40
- **C. Low trust (0.20–0.35):** zombie facts to re-verify or hard-delete

**Hard rules:**
1. **Dry-run table FIRST.** Never execute without user approval.
2. **Sensitive-health (MedicationB, ConditionA, dosing): HOLD.**
3. **Synthesis ceiling: 0.45 max.** Never outrank component facts.
4. **`fact_feedback` only moves trust.** Wrong content needs `fact_store update`.
5. **Stale ≠ wrong.** Check before demoting.
6. **Batch size: 10–20 facts/session max.**

**Common patterns:** Life Event Staleness, Redundancy Detection, Wiki-Memory Reconciliation (optional), Synthesis Fact Rescoring — see `references/four-way-reranking-audit.md` for full details.

**Pass 8 pitfalls:** Don't demote career facts post-EmploymentTransition (consolidate, don't delete). Health Facts Are Sacred (never without explicit confirmation). Policy facts need user clarification. Commute expiry ≠ contract expiry.

**Completion criteria:** dry-run table approved before execution; sensitive-health facts held; synthesis facts below 0.45; summary report delivered.

---

## Audit Procedures (Reference)

The following procedures are NOT sequential passes but discrete operations:

- **Trust Reweighting Audit** (`fact_feedback` dry-run) — 5-phase pattern for nudging trust scores
- **Cross-Store Drift Reconciliation** — propagating fact corrections to wikis/vaults
- **Category Size Escalation Protocol** — per-category thresholds (300 warning, 500 emergency)
- **Defense in Depth: Entity Drift Prevention** — 3-layer alias detection

Full details: `references/audit-procedures.md`.

---

## Rules

1. **Never act without asking.** One issue at a time unless user approves bulk.
2. **Bulk approval:** "yes to all" covers a group of similar fixes — treat single-word replies ("delete", "yes to all") as blanket approval for the issue set just presented, NOT a license to expand scope.
3. **"Skip all" → stop gracefully.**
4. **"Continue without asking" → safe deprecations only. No hard deletes.**
5. **Log each completed action** for the end-of-session summary.
6. **Use the right tool:**
   - Tag correction → `fact_store update(fact_id, tags='new, tags')`
   - Trust nudge (not behavioral signal) → `update(fact_id, trust_delta=±0.1)`
   - Content rewrite → deprecate old + `add` new
   - Behavioral signal → `fact_feedback helpful/unhelpful`
7. **Hard delete directly** when approved — `add` consolidated then `remove` originals; only deprecate first if the user wants an audit trail.

---

## Output Format

### Standard Issue
```
[JANITOR] Issue in #<fact_id>
Type: <unquoted-entity | bundled-fact | cohesion-split | tombstone | encoding-fix>
Content: "<current content>"
Suggestion: <proposed fix>
Action needed: YES to proceed / NO to skip
```

### Rewrite Question
```
[JANITOR] Observation in #<fact_id>
Type: rewrite
Content: "<current content>"
Issue: <what is confusing or could be clearer>
Proposed rewrite: "<new version>"
Ask: YES to apply / NO to leave / SPECIFY your own wording
```
Use only when content is factually correct but structurally unclear.

---

## End of Session Summary
```
[JANITOR] Session Complete
- Issues found: N
- Issues resolved: M
- Hard deletes: K
- Deprecations: D
- Skipped: S
```

---

## LLM Synthesis Guard (Critical — Always Active)

When using an LLM to **decompose, extract, or synthesize** facts:

**The hallucination risk is non-zero even on simple input.** An LLM can fabricate content not present in the source. Trust=0.3 source material does NOT produce trust=0.3 atoms; it can produce confident hallucinations at trust=0.5.

**Required workflow:**
1. **Print raw first** — show LLM output verbatim before writing anything. Do not summarize or assure.
2. **User reviews** — let them flag fabrications, duplicates, mis-categorizations.
3. **Corrections incorporated** before a second write.
4. **Trust reset** — synthesized atoms start at **trust=0.5**, not the source's tombstone trust.
5. **Mark source as reviewed** — `fact_feedback helpful`/`unhelpful` on the source.

**Hallucination signatures:** specific names/dates/numbers absent from source; inferences presented as facts; confidence disproportionate to source quality; topics that "fill gaps" in sparse source. **When caught: discard the hallucinated fact entirely; tell the user.**

---

## Scripts

All scripts use MemoryStore shared connection and `--db` flag for testing.

- `scripts/check_hrr_health.py` — HRR vector integrity audit. Detects inhomogeneous byte-lengths (bank corruption) and NULL vectors (invisible to HRR). Uses MemoryStore, dimension-agnostic. Exit 0 = healthy, 1 = problems.
- `scripts/check_entity_bindings.py` — entity binding rate audit. Derives entity list from the store (frequency floor ≥ 3), computes bound/fts_mentions rate. Exit 0 = all OK, 1 = entities below threshold.
- `scripts/check_fact_discipline.py` — pre-write quoting linter and full store audit. Store-derived entity check, dimension-agnostic capacity warning, HRR homogeneity check. Supports `--dry-run`, `--store`, `--json`.

---

## Common Pitfalls

1. **Acting without asking.** One issue at a time unless user approves bulk.

2. **Verify bindings via `fact_entities`, never via content matching or `probe()`.** `LIKE '%EntityName%'` and `search()` produce false positives. The only reliable check is a `fact_entities` SQL JOIN row linking fact_id to entity_id.

3. **ALL CAPS / single-word capitalized entities fail `_RE_CAPITALIZED`.** The regex requires 2+ title-case words; `ConditionA`, `InsurerC`, `MedicationB`, `User` are invisible unless explicitly double-quoted. **Always quote single-word terms** — mandatory, not redundant.

4. **Entity fragmentation causes wrong bindings.** Bulk/unquoted writes may resolve `"InsurerC"` to a fragmented entity (`InsurerC ProductF`) instead of canonical `InsurerC`. `_resolve_entity` does an exact `LIKE` match, so the fix is `fact_store update` with the canonical `"InsurerC"` in content.

5. **UNIQUE constraint on duplicate-content `update`.** When two facts share content, updating one to add quotes collides with the other (`content` is UNIQUE). Differentiate first (append a parenthetical), then update both.

6. **WAL safety check.** The MemoryStore shared connection (store.py:98-112) prevents cross-connection WAL contention under normal operation. If opening a raw connection, verify with PRAGMA query_only=ON first. A genuine lock (from a gateway restart race) → tell the user, never restart the gateway.

7. **Tombstones (0.3) are passive, not a cleanup queue.** Only act with a concrete reason (duplicate, confirmed error, merge). Pre-compute deprecation cascade: each `unhelpful` subtracts 0.10, so prefer `fact_store update(fact_id, trust_delta=-X)` to set the target directly.

8. **Forgetting category size.** Above 500 facts the contradiction gate is unreliable. Pre-flight per-category counts; keep below 300.

9. **`update` recomputes on ANY content — no byte-equality skip.** `update_fact` guards on `if content is not None`, not on whether content changed. Passing byte-identical content DOES re-extract + rebuild HRR. To change bindings you must **ADD THE QUOTES**.

10. **Empty HRR vector = invisible to the bank.** `_rebuild_bank()` filters `WHERE hrr_vector IS NOT NULL`; null vectors are silently excluded (no error, empty probe results). Fix via `fact_store update` with current content.

11. **Invalid category values silently break category-scoped probe.** Schema enum allows only `user_pref/project/tool/general`. `financial`/`health` facts are accepted but never appear in category-scoped probe. Migrate to valid categories when found.

12. **Kitchen-sink mega-bundles ≠ conceptual bundles.** A single 200+ word fact covering 10+ life domains is a failed synthesis — always atomize (with the LLM Synthesis Guard). Conceptual bundles stay bundled.

---

## Verification Checklist

- [ ] DB health pre-flight: MemoryStore connection verified, schema matches store.py
- [ ] Entity health pre-flight: HRR vectors homogeneous + non-null, binding rates checked
- [ ] Per-category fact counts reported before any pass
- [ ] All 9 passes executed in order (0 Bank Repair → 1 Entity Binding → 2 Bundled → 3 Cohesion → 4 Tombstones → 5 Temporal → 6 Coreference → 7 Neglect → 8 Reranking)
- [ ] Pass 8: dry-run table presented and approved; sensitive-health facts held; synthesis facts below 0.45 ceiling
- [ ] Pass 1 fixes verified via `fact_entities` JOIN / `probe()` before moving on
- [ ] Bulk approvals confirmed with user
- [ ] Category escalation reviewed — no category above 300
- [ ] End-of-session summary delivered
- [ ] No direct SQL writes — all writes via `fact_store`
