# Trust Reweighting Audit and Cross-Store Drift Procedures

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

## Category Size Escalation Protocol

In `retrieval.py:381`, `_MAX_CONTRADICT_FACTS = 500`. Above 500 facts per category, only the 500 most recently updated are checked for contradictions — oldest facts become permanently invisible to the contradiction detector.

| Category size | Status | Action |
|---|---|---|
| 0–300 | Healthy | Normal operation |
| 300–499 | Warning | Flag; begin aggressive hard-delete of low-trust deprecated facts |
| 500+ | Emergency | Contradiction gate compromised; immediate hard-delete sweep |

**Pre-flight count:** get per-category sizes before any pass. Keep all categories below 300 (ideally below 200).

## Defense in Depth: Entity Drift Prevention

**Layer 1 — Real-Time Gate (pre-write, governed by holographic-memory-best-practices):** before every `fact_store add`, probe the canonical entity name; search for aliases; use the canonical name in content; flag missing canonical for Layer 2.

**Layer 2 — Periodic Janitor Scan (interactive):** for each suspected alias pair, intersect dual `probe()` result sets:
```python
probe_a = set(f['fact_id'] for f in fact_store(action='probe', entity='"<NameA>"')['facts'])
probe_b = set(f['fact_id'] for f in fact_store(action='probe', entity='"<NameB>"')['facts'])
if probe_a & probe_b:  # same entity under two names → migrate to canonical
```
**Layer 3 — Encoding Fixes (extraction failures):** entity never quoted at write-time → quote it via `fact_store update`; the call re-runs `_extract_entities()` and creates the binding.
