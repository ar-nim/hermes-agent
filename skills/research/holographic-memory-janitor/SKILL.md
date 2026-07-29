---
name: holographic-memory-janitor
description: >-
  Use when running interactive maintenance on the holographic memory store —
  cleanup, audit, deduplication, integrity checks, or the 4-way reranking
  audit (fact verification against session history, skills, optional wiki,
  and fact_store self-consistency). Corrective and reactive. For autonomous
  synthesis, use holographic-memory-reflect instead.
version: 2.7.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [memory, fact-store, holographic, maintenance, janitor, reranking, audit]
    related_skills: [holographic-memory-best-practices, holographic-memory-reflect]
---

# Holographic Memory Janitor: Interactive Maintenance

## Overview

The janitor is the **corrective maintenance layer** for the holographic fact store. It is interactive and reactive — it fixes problems flagged by the user or by automated trigger checks (e.g., seed anchors below trust threshold). It asks before every action and produces an end-of-session summary of what was done.

Unlike the reflect skill (generative, autonomous, cron-triggered), the janitor is directed by the user and operates on existing facts. Both are operationally distinct — they cannot be merged.

## When to Use

- User says "run the janitor" or "run holographic memory maintenance"
- Automated trigger reports seed anchors below threshold
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

## Pre-Flight: WAL Lock Check

Before starting, check for uncommitted WAL transactions:
```bash
fuser "$HERMES_HOME/memory_store.db"
ls -la "$HERMES_HOME/memory_store.db-wal"
```

**WAL safety with MemoryStore shared connection.** The holographic memory plugin (`store.py:98-112`) uses a process-wide shared connection pool. All `MemoryStore` instances for the same DB share ONE connection with a re-entrant lock — cross-connection WAL contention is impossible. Janitor audit scripts that open their own `sqlite3.connect()` with `PRAGMA query_only=ON` are still safe (WAL allows concurrent readers), but prefer the shared connection when writing. See `reflect_pipeline.get_store()` for the canonical pattern.

**Stale WAL + new gateway PID = false positive.** A PID in `fuser` output does not always mean the gateway is actively writing. If the WAL timestamp predates the current gateway session, the lock may be stale. Always verify with a MemoryStore read-only query:
```bash
python3 -c "
from store import MemoryStore
import os
store = MemoryStore()
count = store._conn.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
print('READ OK,', count, 'facts')
store.close()
"
```
If the read succeeds → WAL is stale; proceed. If it fails with `database is locked` → gateway holds exclusive write lock → tell user to restart gateway, wait, retry.

**⚠️ NEVER restart the gateway yourself.** The user has explicitly forbidden gateway restarts by the agent. When a genuine lock is detected, tell the user and wait for them to restart, then retry.

## Pre-Flight: Load Full Best-Practices

Before beginning, load the operating engine:
```bash
skill_view(name='holographic-memory-best-practices')
```

## Pre-Flight: Schema Verification

Verify the actual DB schema matches `store.py` before starting. All janitor recommendations (hard deletes, deprecations, splits) depend on the schema behaving as expected.
```python
from store import MemoryStore
import os
store = MemoryStore()
rows = store._conn.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for r in rows:
    print(r[0])
store.close()
```
**Critical path distinction:** always use `$HERMES_HOME/memory_store.db` (SQLite) in cron. The `DuckDB` file at a different path yields "Table with name facts does not exist".

Verify:
1. `content TEXT NOT NULL UNIQUE` — the UNIQUE constraint is the deduplication mechanism
2. Tables: `facts`, `entities`, `fact_entities`, `facts_fts`, `memory_banks`
3. FTS triggers present and correct

If anything deviates from `store.py`, report it before proceeding.

## Pre-Flight: Bank Integrity Check

**Run this BEFORE the seed anchor check.** A corrupt bank makes every subsequent `probe()` and `add` fail with a confusing numpy error.

```bash
python3 skills/holographic-memory-janitor/scripts/check_bank_integrity.py
```

Per-category byte-length audit of `hrr_vector`. Expected byte length is `hrr_dim * 8` (float64) — read `hrr_dim` from config.yaml; do NOT hardcode 4096. At the 1024-dim default this is 8192 bytes; at 4096-dim it is 32768.
```
user_pref: 227 vectors, byte_lens={32768: 224, 8192: 3} ✗ CORRUPT
  #831 byte_len=8192 (expected 32768)
```
**If corruption is detected:** stop and run Pass 0 before any other pass. See `references/bank-corruption-diagnosis.md` for the full root-cause analysis.

Also run `scripts/check_null_hrr_vectors.py` (per-category `hrr_vector IS NULL` audit) when the byte-length check returns clean — catches the silent "excluded from bank" failure mode.

## Pre-Flight: Seed Anchor Trigger Check

Determine if the janitor is needed:
```bash
python3 skills/holographic-memory-janitor/scripts/check_anchors.py
```
```
ConditionA: 0.000 (TRIGGER) — 0/45 bound, threshold=0.9, gap=0.9, critical=True
```
If all anchors OK → "All anchors healthy." If triggers found → report to user for an interactive janitor session.

**The "0 seed anchors" case:** "Found 0 seed anchors" + "All anchors healthy" is NOT a clean bill of health — it is a silent false-negative. Stores without seed anchors must rely on other pre-flight signals (bank integrity, FTS drift, entity density). Do not skip pre-flight just because the anchor check returned a green line.

**Recovery when anchors are missing:** re-seed them as `seed_anchor` facts (content `seed_anchor: <Name>, threshold=0.85, critical=<true|false>`). Pick names from the top-N entities by `bound_count`; do not re-derive thresholds from a vacuum.

## Pre-Flight: Orphan Bank Row Audit

The schema enum only allows `category IN ('user_pref', 'project', 'tool', 'general')`. Post-migration, `memory_banks` rows for `cat:financial` / `cat:health` may be left behind as orphans (bank_name present, zero facts reference it).

**Detection:**
```python
banks = [r["bank_name"] for r in conn.execute("SELECT bank_name FROM memory_banks").fetchall()]
for b in banks:
    cat = b.replace("cat:", "")
    count = conn.execute("SELECT COUNT(*) FROM facts WHERE category = ?", (cat,)).fetchone()[0]
    if count == 0:
        print(f"ORPHAN: {b} (0 facts)")
```
**Cleanup:** Direct SQL DELETE on `memory_banks` is acceptable for orphan rows (no facts to migrate, no vector to recompute) — this is the one case where direct SQL writes are correct:
```python
conn.execute("DELETE FROM memory_banks WHERE bank_name IN ('cat:financial', 'cat:health')")
conn.commit()
```

---

## DB Access Rules

- **MemoryStore shared connection** — the holographic memory plugin (store.py:98-112) uses a process-wide shared connection pool. All MemoryStore instances share ONE connection with a re-entrant lock, eliminating cross-connection WAL contention. The gateway, janitor scripts, and reflect pipeline all join this pool when they use get_store() / MemoryStore(db_path=...).
- **All writes** → fact_store tool (uses gateway's own connection, available in interactive sessions).
- **Simple reads (probe, search)** → fact_store tool.
- **Cron environment reads** → terminal with sqlite3 CLI or a MemoryStore script (preferred). The sqlite3 CLI is a standalone binary, not flagged as script execution.
- **Cron execution pattern blocks (verified):** execute_code, inline python3 -c, and rm /tmp/... are BLOCKED in cron. Use sqlite3 $HERMES_HOME/.hermes/memory_store.db "SQL" or write a script to /tmp/x.py and run python3 /tmp/x.py.
- **WAL safety:** the shared connection eliminates cross-process WAL contention (see WAL pre-flight section above). Never restart the gateway yourself.
- **Two-phase fix for entity quoting:** Phase 1 (bulk quoting via SQLite SQL) computes new quoted content strings for all unbound facts; Phase 2 (`fact_store update` per fact) is mandatory — it triggers `_extract_entities()` AND `_compute_hrr_vector()`. Never skip Phase 2 (`fact_entities` and `hrr_vector` are separate; correct links without a fresh HRR vector still score poorly). The UNIQUE constraint hazard: if two facts share content after quoting, differentiate (append a parenthetical) before updating both.
- **Exception — Pass 1 discovery only:** the entity density JOIN query has no built-in tool equivalent; `execute_code` is acceptable strictly for discovery, not verification or fixes.

---

## The Janitor Loop

For each category, execute passes in order. Complete one pass before starting the next. **Pass 0 runs only if the bank integrity pre-flight flagged corruption.** Skip it on a clean store. **Pass 8 (4-Way Reranking Audit) is store-wide rather than per-category** — run it as the closing pass of a full janitor session, or standalone when the user asks for a "reranking audit".

### Pass 0: Bank Integrity Repair

**Problem:** a fact has `hrr_vector` at a different dimensionality (in bytes / 8) than the rest of the bank. When `_rebuild_bank()` bundles vectors, numpy rejects the inhomogeneous list; every subsequent `add` / `update` / `probe` in that category fails with `setting an array element with a sequence. The requested array has an inhomogeneous shape after 1 dimensions.`

**Root cause:** the `holographic-memory-reflect` pipeline instantiated `HolographicStore()` without reading `hrr_dim` from `config.yaml`, so the constructor default (`store.py:105: hrr_dim: int = 1024`) won, writing vectors at a different `hrr_dim` than the bank (e.g. the 1024-dim constructor default into a config-set 4096-dim bank, or vice-versa).

**Procedure — the "last update succeeds" pattern:**
`update_fact()` runs in this order: (1) `UPDATE facts SET content=...`; (2) re-extract + re-link entities if `content is not None`; (3) `_compute_hrr_vector()` — **commits a fresh vector at the correct dim BEFORE the bank rebuild**; (4) `_rebuild_bank()` — **may FAIL while any sibling vector is still wrong-dim**. So even when `update` returns the rebuild error, the targeted fact's vector is already recomputed at the correct dim. Only the FINAL update (removing the last outlier) returns `{"updated": true}`. The first N-1 errors are expected and non-fatal.

For each corrupt fact returned by `check_bank_integrity.py`:
```bash
fact_store(action='update', fact_id=<N>, content=<verbatim current content>)
```

**Do not pre-emptively modify the content.** `update_fact` has no byte-equality check (guard is `if content is not None`); passing the verbatim current string DOES trigger recompute. The myth that "byte-identical content skips recompute" is false — the guard is `content is not None`, not a diff check. (To fix dimension corruption, pass the verbatim content; the vector is rewritten at the correct dim.)

**Completion criteria:**
```bash
python3 scripts/check_bank_integrity.py   # → "All banks homogeneous."
sqlite3 "$HERMES_HOME/memory_store.db" \
  "SELECT bank_name, dim, fact_count, length(vector) FROM memory_banks WHERE bank_name='cat:user_pref'"
# length(vector) = hrr_dim * 8 — read hrr_dim from config.yaml
fact_store(action='probe', entity='"User"', category='user_pref', limit=3)   # works
fact_store(action='add', content='test', category='user_pref', tags='test')
fact_store(action='remove', fact_id=<new_id>)
```
**Prevention:** the reflect pipeline must read `hrr_dim` from `config.yaml` before instantiating `HolographicStore()`. See `references/bank-corruption-diagnosis.md` for the full RCA.

### Pass 1: Entity Extraction Hygiene

**Problem:** Unquoted entities are never extracted by `_extract_entities()` — they get zero HRR binding. Every fact containing an important entity must quote it in its content.

**Seed anchors** are the primary enforcement target — stored as facts tagged `seed_anchor` (not hardcoded). To add/remove one, use `fact_store add/remove`.

**Per-entity miss-rate (the real metric):** global unbound percentage is a vanity metric. For each seed anchor, compute bound/total:
```python
import sqlite3, os
conn = sqlite3.connect(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/memory_store.db")
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
# seed_anchors loaded from store (facts WHERE tags LIKE '%seed_anchor%')
for name, threshold, seed_fid in seed_anchors:
    total = conn.execute("SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ? AND rowid != ?", (f'"{name}"', seed_fid)).fetchone()[0]
    bound = conn.execute("SELECT COUNT(*) FROM fact_entities fe JOIN entities e ON e.entity_id=fe.entity_id WHERE e.name=?", (name,)).fetchone()[0]
    rate = round(bound/total, 3) if total > 0 else None
    print(f"{name}: {rate} ({bound}/{total})")
```
If `bound/total < threshold` for any anchor → trigger.

**Word-boundary rule:** use `(?<!\")\\bentity\\b(?!\"])` — don't match already-quoted entities, don't treat substrings as matches.

**Empirical finding:** content containing an entity name does NOT mean it is bound in `fact_entities`. Always verify binding via direct SQL JOIN, never infer from content. Single-word capitalized / ALL CAPS terms (`User`, `ConditionA`, `MedicationB`, `InsurerC`, `LocalTZ`) are NOT auto-extracted by `_RE_CAPITALIZED` (requires 2+ title-case words) — they must be explicitly double-quoted.

**Fix:** For each unbound fact, ask the user to quote the entity; bulk approval ("yes to all") covers a group.
```
[JANITOR] #<fact_id> — unquoted entities: <list>
Content: "<current content>"
Entity bindings: <list from SQL — may be empty even though content mentions the entity>
Fix: quote each unquoted entity name in content
Action needed: YES to apply / NO to skip
```

**Completion criteria:** Pass 1 fixes verified via `probe()` (and `fact_entities` SQL JOIN) before moving on; per-anchor bound/total at or above threshold.

### Pass 1b: Bulk Entity Binding (Zero-Entity Facts)

**Problem:** Facts with zero `fact_entities` bindings (written before extraction worked, or with no extractable entities) are invisible to `probe()` / `reason()` / `related()`, and cause bank count mismatches. Scale: can exceed 100 facts in a mature store.

**Root cause:** `_RE_CAPITALIZED` requires 2+ capitalized words. Single-word terms (`User`, `ConditionA`, `MedicationB`, `InsurerC`, `LocalTZ`, `GCP`) are not auto-extracted — must be explicitly double-quoted.

**Detection:**
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

**Fix procedure:**
1. Identify facts with no double-quoted terms and no multi-word title-case phrases.
2. Add double quotes around the most important entity (e.g. `"User"` for user_pref, `"EmployerE"` for work facts).
3. `fact_store update` with quoted content → triggers `_extract_entities()` → `_resolve_entity()` → `_link_fact_entity()` → `_compute_hrr_vector()`.
4. Batch 5-10 per tool call.
5. Verify bindings via `fact_entities` SQL after each batch.

**Critical (verified):** `update_fact` recomputes HRR vector + re-extracts entities on ANY `content` argument — the guard is `if content is not None`, NOT byte-equality. There is **no byte-equality skip**. The June-20 observation (181 "updates" with identical content produced no bindings) happened because the **same unquoted** text re-extracts deterministically to empty. To add bindings you must **ADD THE QUOTES**. So: pass `content` with the quotes added; passing byte-identical unquoted content returns `{"updated": true}` but yields no new bindings (the recompute ran, found nothing new).

**Completion criteria:** zero-entity facts now have `fact_entities` rows (verified via SQL JOIN) and fresh HRR vectors.

### Pass 2: Bundled Facts (Atomicity Violations)

**Problem:** Multiple independent claims stored as one fact pollute HRR retrieval — a query for A returns B's noise.

**Detection:** `§` separator = always bundled. Also scan long (300+ char) multi-claim facts.

**Tight-coupling principle — DO atomize (format-bundled):** `§`-separated sections, multi-session captures of the same event, P0 incident duplicates, kitchen-sink mega-bundles (10+ unrelated life domains), one-liner summaries fully superseded by a detailed sibling.

**DO NOT atomize (conceptual bundles):** identity snapshots (job, income, family health, travel, medication organically coupled), medical management protocols, system configuration facts, user preference clusters forming a coherent philosophy, user-confirmed coupled claims. The user is the authority.

**MANDATORY: show raw content before asking.** Present the exact content and entities via SQL; never pre-filter or summarize. The user decides conceptual-coupling vs format-bundling.

**Pass 1 pre-check before any `fact_store update`:** if two facts share the same content string, the later update fails with `UNIQUE constraint failed`. Differentiate (append a parenthetical) before updating.

**Mega-bundle cleanup:** (1) search the store for each component; (2) track — already-an-atom (no action) / genuinely-new (save standalone) / partial-overlap (offer rewrite, don't deprecate without saving); (3) deprecate the mega-bundle only after all new components are secured; (4) do NOT re-bundle existing atoms. Extracted atoms start at trust 0.4 (tag `unverified-source`) until user-confirmed → 0.5.

**Fix:** present raw content, ask split / keep / specify.

**Completion criteria:** user decisions recorded; all genuinely-new components secured as standalone atoms before the bundle is deprecated.

### Pass 3: Cohesion Violations

**Problem:** Related claims scattered across multiple facts that should travel together.

**Procedure:** Present raw content (not tables — tables strip context) for each candidate and let the user decide merge / keep separate / deprecate. Verify bundle components against the store via `probe()` / `search()` before presenting a demotion (a prior session may have partially atomized).

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

**Hard-delete-first rule:** prefer `fact_store remove` (reclaims the full vector slot). Deprecate (`fact_feedback unhelpful`) only when the old fact has specific historical query value. Pre-compute the target trust before mass deprecation: each `unhelpful` subtracts 0.10, so from 0.3 deprecate once for a 0.1 floor, at most 3× for full deprecation; better, use `fact_store update(fact_id, trust_delta=-X)` to set the target directly.

**Fix:** ask the user per candidate (DELETE / LEAVE AS-IS).

**Completion criteria:** candidates resolved per user; no systematic 0.3-tier sweep.

### Pass 5: Temporal Consistency Audit

**Purpose:** Detect outdated facts, flag superseded sequences, propose trajectory updates. The plugin has no built-in temporal reasoning; this pass scans content strings for ISO 8601 dates.

**Procedure:**
1. Scan content for `\\b\\d{4}-\\d{2}-\\d{2}\\b`.
2. Group facts by shared entity (via `fact_entities` / `probe()`).
3. For each entity with ≥2 dated facts, sort by embedded date.
4. Flag sequences where a newer fact contradicts an older one without trajectory format.
5. Propose update with Trajectory Format: `"[New state] (previously: [old state])"`.

**Implementation (computation-only, no LLM):**
```python
import re, sqlite3, os
from datetime import datetime
conn = sqlite3.connect(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/memory_store.db")
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
ISO_DATE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
dated = []
for row in conn.execute("SELECT fact_id, content FROM facts").fetchall():
    ds = sorted(set(ISO_DATE.findall(row['content'])))
    if ds: dated.append({'fact_id': row['fact_id'], 'dates': ds})
# group by entity via fact_entities, then for each entity with >=2 facts sort and flag
```

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

**Issue format:**
```
[JANITOR] #<fact_id> — potential coreference
Content: "<current content>"
Detected alias: "<alias>" for entity "<canonical>"
Proposed binding: "<canonical> aka <alias>"
Action needed: YES to add binding / NO to skip
```
**RULE: Never auto-create bindings. Always ask.**

**Completion criteria:** proposed bindings confirmed by the user before any write.

### Pass 7: Neglect Detection (retrieval_count Awareness)

**Purpose:** Identify facts never retrieved (`retrieval_count` increments on search/probe/related/reason — observability ONLY, never scoring/ranking). These facts may need HRR recompute, entity re-quoting, or pruning.

**Prerequisite:** `retrieval_count` must be incrementing (confirm via `SELECT MAX(retrieval_count) FROM facts` > 0). If zero on all facts, the PR #73901 fix may not be deployed — skip this pass.

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

**Purpose:** Systematic audit of facts against four independent sources for accuracy, staleness, and contradictions. Designed for periodic maintenance (monthly/quarterly) or triggered by major life events (EmploymentTransition, marriage, relocation) that stale entire clusters of facts at once. Broader than the Trust Reweighting Audit below: it can also remove and update facts, not just nudge trust.

Full batch mechanics and validated workflow: `references/four-way-reranking-audit.md`.

**Sources (authority order):**
1. **Session history** — what the user explicitly said/confirmed (`session_search`)
2. **Skills** — ground-truth schedules, endpoints, cron IDs, protocols (`skill_view`)
3. **Optional external wiki (llm-wiki)** — if installed, compiled knowledge from default + profile wikis. Skip if no wiki is configured.
4. **Fact_store** — self-consistency via `contradict()` and `reason()`

**Method — for each candidate fact,** query ALL four sources and assign a signal:

| Signal | Meaning | Action |
|--------|---------|--------|
| ✅ Corroborated | multiple sources agree | `fact_feedback(action='helpful')` — promotes trust |
| ⚠️ Mixed/Silent/Sensitive | unclear or health-related | NO CHANGE — hold (see Trust Reweighting critical rule 2) |
| 🔴 Contradicted | sources disagree | `fact_feedback(action='unhelpful')`; if content wrong, flag for update |
| 💀 Obsolete | no longer applies to current reality | `fact_store(action='remove')` — user-approved only |
| 🔄 Update | content changed | `fact_store(action='update')` with Trajectory Format: "[Current] (previously [Old])" |

**Candidate tiers:**
- **A. High trust (≥0.55):** verify they're still correct
- **B. Synthesis facts (<0.40):** promote cross-domain gems to 0.35–0.40
- **C. Low trust (0.20–0.35):** zombie facts to re-verify or hard-delete

**Hard rules:**
1. **Dry-run table FIRST.** Never execute without user approval (same discipline as the Trust Reweighting Audit's 5-phase pattern).
2. **Sensitive-health (MedicationB, ConditionA, dosing): HOLD.** Requires explicit confirmation — see Health Facts Are Sacred below.
3. **Synthesis ceiling: 0.45 max.** Never outrank component facts.
4. **`fact_feedback` only moves trust.** Wrong content needs `fact_store update`.
5. **Stale ≠ wrong.** Check before demoting.
6. **Cross-profile:** PartnerWiki often more current on life-event/relationship facts.
7. **Batch size: 10–20 facts/session max.** Don't overwhelm.

**Dry-run table format:**
```markdown
| fact_id | Content (80 chars) | Trust | Evidence | Proposed | Rationale |
```

**Execution:** Pre-audit — `fact_store list` inventory, `contradict()` per category, `session_search` for recent confirmations, `skill_view` for cross-reference. During — per 10–20-fact batch: cross-reference all 4 sources → build dry-run table → user approval → execute → boost verified facts → trajectory-format updates. Post — summary report (audited/boosted/demoted/updated/removed/held), flag cross-source drift for followup (wiki-sync only if a wiki is configured).

**Common patterns:**

- **Life Event Staleness.** A major life event stales whole clusters simultaneously — EmploymentTransition: commute facts, work schedule, office location, compensation, employment status; marriage: girlfriend/Partner references, single-status assumptions; relocation: home location, transit routes, weather zone. Approach: recognize the cluster, demote the whole group, update the canonical identity fact, consolidate history into fewer, richer facts.
- **Redundancy Detection.** Same content in multiple facts, subset relationships (fact A fully contained in fact B), near-duplicate quotes across fact IDs. Keep the most comprehensive/specific version; demote the rest.
- **Wiki-Memory Reconciliation (optional — only if llm-wiki is installed).** fact_store is source of truth; the wiki is the compiled, human-readable version. After fact updates, propagate: `entities/<name>.md` (identity, career), `index.md` (summary lines), `log.md` (audit trail). Skip entirely if no wiki is configured. See also Cross-Store Drift Reconciliation below.
- **Synthesis Fact Rescoring.** Rescore `reflect-synthesis` facts (trust 0.30–0.40) when real-world events validate them, they duplicate another synthesis fact, or they become moot. Ceiling: 0.45 — never outrank component facts.

**Pass 8 pitfalls:**

- **Don't demote career facts post-EmploymentTransition.** Work experience is career capital for job seeking. Consolidate scattered work facts into one comprehensive career summary; demote purely operational facts (monitoring dashboards, daily schedule); keep tech stack, achievements, scope — these feed resume/application material.
- **Health Facts Are Sacred.** MedicationB, ConditionA, dosing, interactions — never demote or update without explicit user confirmation (Trust Reweighting critical rule 2). Mark HOLD and move on.
- **Policy facts need user clarification.** Insurance policy types (critical illness vs life vs health) may be ambiguous. Always ask before modifying policy/financial facts.
- **Commute expiry ≠ contract expiry.** A contract may say "last day [DATE]" but the person stopped commuting at announcement. Don't assume commute facts are valid until contract end — ask "When did you last actually commute?"

**Completion criteria:** dry-run table approved before execution; sensitive-health facts held; synthesis facts below 0.45; summary report delivered.

---

## Defense in Depth: Entity Drift Prevention

**Layer 1 — Real-Time Gate (pre-write, governed by holographic-memory-best-practices):** before every `fact_store add`, probe the canonical entity name; search for aliases; use the canonical name in content; flag missing canonical for Layer 2.

**Layer 2 — Periodic Janitor Scan (interactive):** for each suspected alias pair, intersect dual `probe()` result sets:
```python
probe_a = set(f['fact_id'] for f in fact_store(action='probe', entity='"<NameA>"')['facts'])
probe_b = set(f['fact_id'] for f in fact_store(action='probe', entity='"<NameB>"')['facts'])
if probe_a & probe_b:  # same entity under two names → migrate to canonical
```
**Layer 3 — Encoding Fixes (extraction failures):** entity never quoted at write-time → quote it via `fact_store update`; the call re-runs `_extract_entities()` and creates the binding.

## Trust Reweighting Audit (`fact_feedback` dry-run)

A discrete janitor operation (NOT a pass in the 0–8 sequence, and NOT the reflect pipeline which *writes* new facts at trust 0.3). Runs when the user asks to "train" or "audit" the store. Output: `fact_feedback` calls that nudge `trust_score`. For the broader 4-source audit that can also remove/update facts, use Pass 8.

**The 5-phase pattern (verified):**
| Phase | Action | Tool |
|-------|--------|------|
| 1. Gather | Pull candidate facts grouped by entity, ordered by `probe` score | `fact_store probe "<Entity>" limit=N` |
| 2. Cross-check sessions | What User actually said/confirmed | `session_search` (read-only) |
| 3. Cross-check external wiki(s) [optional] | If llm-wiki installed: canonical record — default + profile wikis | `search_files` (read-only); skip if no wiki |
| 4. Dry-run table | fact_id, current trust, evidence, proposed action, rationale | `clarify` (user) |
| 5. Execute | One `fact_feedback` per approved row | `fact_feedback` |

**Critical rules:**
1. **Always dry-run, never batch-write.** Present the full table, get approval, then execute. `fact_feedback` is irreversible without a backup.
2. **Hard rule against moving sensitive-health claims.** Missed-dose / adherence claims require explicit user time/timestamp confirmation. Do not move on inference alone.
3. **`fact_feedback` is NOT for content updates.** Wrong date/budget/ROM → `fact_store update` (triggers re-extraction + HRR recompute). `fact_feedback` only nudges trust.
4. **Stale ≠ untrustworthy.** A 5-week-old fact about a broken system may still be correct — archive or update, don't demote.
5. **Duplicates need the janitor, not fact_feedback.** Pick a canonical, `fact_store remove` the other.
6. **Cross-check sibling profile wikis [if configured].** When profile wikis exist, the shared profile wiki is often *more* current than `default` on shared facts.
7. **`helpful`/`unhelpful` deltas are small but real** (~0.05–0.1). Multiple corroborating calls compound.

**Output format:**
```
| fact_id | Current | Evidence signal | Proposed | Rationale |
| 335 | 0.50 | 🔴 Contradicted (shared wiki + 3 sessions) | unhelpful | Wrong date AND budget |
```
Use ✅ (confirmed), ⚠️ (mixed/sensitive/hold), 🔴 (contradicted).
**Cost preview:** N `fact_feedback` writes, 0 `fact_store` writes, 0 integrity check needed.

## Cross-Store Drift Reconciliation (follow-up to reweighting audit)

`fact_feedback` only touches fact_store. When the audit surfaces a fact whose content disagrees with the user's **other configured stores** (default wiki if llm-wiki is installed, profile wikis, external note vaults (e.g. Joplin, Obsidian) if present), the trust nudge is the first step, not the end.

**The 4-step recipe (verified):**
1. **Audit all configured stores** for the stale claim — `grep` across whichever wikis/vaults exist (skip stores that aren't set up).
2. **Establish source-of-truth** explicitly (newer sources generally supersede older; sibling wiki, when present, often more current on shared facts).
3. **Patch each existing store top-to-bottom:** `fact_store` (trust via `fact_feedback` / content via `fact_store update`) → default wiki (`patch`, if installed) → sibling wikis (if any) → schema/index (`last_updated` bump). Only patch stores that actually exist.
4. **Document the de-dup convention** (e.g. `concepts/wiki-coordination.md`) so it doesn't recur.

**What this is NOT:** not a merge (multi-profile privacy boundary); not a fact_store-only job (wiki reconciliation needs `llm-wiki` installed — skip the wiki half if absent); not automatic (drift in an unqueried store won't be caught).

---

## Category Size Escalation Protocol

In `retrieval.py:381`, `_MAX_CONTRADICT_FACTS = 500`. Above 500 facts per category, only the 500 most recently updated are checked for contradictions — oldest facts become permanently invisible to the contradiction detector.

| Category size | Status | Action |
|---|---|---|
| 0–300 | Healthy | Normal operation |
| 300–499 | Warning | Flag; begin aggressive hard-delete of low-trust deprecated facts |
| 500+ | Emergency | Contradiction gate compromised; immediate hard-delete sweep |

**Pre-flight count:** get per-category sizes before any pass. Keep all categories below 300 (ideally below 200).

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

**The hallucination risk is non-zero even on simple input.** An LLM can fabricate content not present in the source (e.g., inventing a "brother died" claim from an ambiguous identity fact). Trust=0.3 source material does NOT produce trust=0.3 atoms; it can produce confident hallucinations at trust=0.5.

**Required workflow:**
1. **Print raw first** — show LLM output verbatim before writing anything. Do not summarize or assure.
2. **User reviews** — let them flag fabrications, duplicates, mis-categorizations.
3. **Corrections incorporated** before a second write.
4. **Trust reset** — synthesized atoms start at **trust=0.5**, not the source's tombstone trust.
5. **Mark source as reviewed** — `fact_feedback helpful`/`unhelpful` on the source.

**Hallucination signatures:** specific names/dates/numbers absent from source; inferences presented as facts; confidence disproportionate to source quality; topics that "fill gaps" in sparse source. **When caught: discard the hallucinated fact entirely; tell the user.**

---

## Scripts

- `scripts/check_anchors.py` — per-anchor bound/total ratio check. Re-runnable; surfaces seed anchors below threshold.
- `scripts/check_bank_integrity.py` — per-category HRR vector byte-length audit. Detects inhomogeneous-shape bank corruption. Run in every pre-flight BEFORE the seed-anchor check. Exit 0 = clean, 1 = corruption.
- `scripts/check_null_hrr_vectors.py` — per-category `hrr_vector IS NULL` audit. Complements the byte-length check; catches reflect-pipeline writes committed without a vector.

---

## Common Pitfalls

1. **Acting without asking.** One issue at a time unless the user approves bulk.

2. **Verify bindings via `fact_entities`, never via content matching or `probe()`.** `LIKE '%EntityName%'` and `search()` produce false positives (e.g. an insurance tenant identifier in a tag, or an already-quoted entity). `probe("ConditionA")` returning a result does NOT prove correct binding — it may be high-confidence noise. The only reliable check is a `fact_entities` SQL JOIN row linking fact_id to entity_id.

3. **ALL CAPS / single-word capitalized entities fail `_RE_CAPITALIZED`.** The regex requires 2+ title-case words; `ConditionA`, `InsurerC`, `MedicationB`, `User` are invisible unless explicitly double-quoted. **Always quote single-word terms** — mandatory, not redundant.

4. **Entity fragmentation causes wrong bindings.** Bulk/unquoted writes may resolve `"InsurerC"` to a fragmented entity (`InsurerC ProductF`) instead of canonical `InsurerC`. `_resolve_entity` does an exact `LIKE` match, so the fix is `fact_store update` with the canonical `"InsurerC"` in content.

5. **UNIQUE constraint on duplicate-content `update`.** When two facts share content, updating one to add quotes collides with the other (`content` is UNIQUE). Differentiate first (append a parenthetical), then update both.

6. **WAL safety check.** The MemoryStore shared connection (store.py:98-112) prevents cross-connection WAL contention under normal operation. If opening a raw connection, verify with PRAGMA query_only=ON first. A genuine lock (from a gateway restart race) → tell the user, never restart the gateway.

7. **Tombstones (0.3) are passive, not a cleanup queue.** Only act with a concrete reason (duplicate, confirmed error, merge). Pre-compute deprecation cascade: each `unhelpful` subtracts 0.10, so prefer `fact_store update(fact_id, trust_delta=-X)` to set the target directly.

8. **Forgetting category size.** Above 500 facts the contradiction gate is unreliable. Pre-flight per-category counts; keep below 300.

9. **`update` recomputes on ANY content — no byte-equality skip.** `update_fact` guards on `if content is not None`, not on whether content changed. Passing byte-identical content DOES re-extract + rebuild HRR. The June-20 "no new bindings" result happened because the **same unquoted** text re-extracts deterministically to empty — to change bindings you must **ADD THE QUOTES**. This corrects earlier drafts (and former pitfalls 19/21) that claimed "identical content is a no-op for binding": the recompute is NOT skipped; identical unquoted text simply re-extracts to the same empty set.

10. **Empty HRR vector = invisible to the bank.** `_rebuild_bank()` filters `WHERE hrr_vector IS NOT NULL`; null vectors are silently excluded (no error, empty probe results). Fix via `fact_store update` with current content; always route writes through `fact_store`, never direct SQL.

11. **Invalid category values silently break category-scoped probe.** Schema enum allows only `user_pref/project/tool/general`. `financial`/`health` facts are accepted but never appear in category-scoped probe. Migrate to valid categories when found.

12. **Kitchen-sink mega-bundles ≠ conceptual bundles.** A single 200+ word fact covering 10+ life domains (work, health, finances, tools, relationships, diet) is a failed synthesis — always atomize (with the LLM Synthesis Guard). Conceptual bundles (identity snapshot, medical protocol, system config, preference cluster) stay bundled.

---

## Verification Checklist

- [ ] WAL lock check run — no gateway PID holding exclusive lock (or stale-lock verified)
- [ ] Schema verification completed — tables/columns match `store.py`
- [ ] **HRR bank integrity verified** — all `hrr_vector`s same byte length (hrr_dim × 8)
- [ ] **No orphan `memory_banks` rows** — every bank_name has ≥1 fact
- [ ] Per-category fact counts reported before any pass
- [ ] All 9 passes executed in order (0 Bank Repair → 1 Entity Extraction → 1b Bulk Binding → 2 Bundled → 3 Cohesion → 4 Tombstones → 5 Temporal → 6 Coreference → 7 Neglect → 8 Reranking Audit)
- [ ] Pass 8: dry-run table presented and approved before any execution; sensitive-health facts marked HOLD; synthesis facts below 0.45 ceiling; career facts consolidated (not blindly demoted) after EmploymentTransition; wiki propagation + log.md audit trail (only if llm-wiki is installed)
- [ ] Pass 1 fixes verified via `fact_entities` JOIN / `probe()` before moving on
- [ ] Bulk approvals confirmed with user
- [ ] Entity alias pairs checked via dual-probe before migration
- [ ] Category escalation reviewed — no category above 300
- [ ] End-of-session summary delivered
- [ ] No `execute_code sqlite3` writes — all writes via `fact_store`
- [ ] No direct SQL on `facts` — orphan `memory_banks` cleanup is the only exception
