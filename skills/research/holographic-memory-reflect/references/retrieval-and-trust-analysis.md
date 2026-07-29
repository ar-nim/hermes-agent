# Retrieval Counter Bug & Trust Scoring Structural Analysis

## Retrieval Count Bug

**Symptom:** `retrieval_count` and `helpful_count` are zero for every fact in `memory_store.db`.

**Root cause:** `retrieval.py::_fts_candidates()` (around line 481) opens raw SQL against `self.store._conn`:

```sql
SELECT f.*, facts_fts.rank as fts_rank_raw
FROM facts_fts
JOIN facts f ON f.fact_id = facts_fts.rowid
WHERE facts_fts MATCH ?
...
```

It never calls `store.search_facts()`, which at lines 231-238 performs:

```python
self._conn.execute(
    "UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN (...)"
)
```

**Call chain:**
- `prefetch()` → `retriever.search()` → `_fts_candidates()` → raw SQL → ❌ no counter
- `fact_store search` → `retriever.search()` → `_fts_candidates()` → raw SQL → ❌ no counter
- `fact_store probe/related/reason` → similar bypass

**Fix options:**
1. **Wire the counter:** Add `UPDATE facts SET retrieval_count = retrieval_count + 1` inside `_fts_candidates()` after fetch.
2. **Merge paths:** Have `FactRetriever.search()` call `store.search_facts()` for FTS5, then apply Jaccard/HRR reranking.
3. **Delete the columns:** If feedback/trust movement is not actually used, remove `retrieval_count` and `helpful_count` to avoid fiction.

## Structural Suppression of Synthesis Facts

**Scoring formula:** `retrieval.py::search()` (around line 97):
```python
score = relevance * fact["trust_score"]
relevance = fts_weight * fts_score + jaccard_weight * jaccard + hrr_weight * hrr_sim
```

**Effect:** Synthesis facts have `trust_score = 0.3`. Regular facts have `trust_score >= 0.5`. A synthesis fact must be **~1.67× more relevant** than a regular fact to tie in score. Because synthesis facts often share keywords with their source facts, they rarely overcome this handicap.

**Result:** Synthesis facts never surface through normal `prefetch()` / `search()` scoring.

## Three Architectures for Synthesis Surfacing

| Model | Trust | Feedback | Mechanism |
|-------|-------|----------|-----------|
| **Hook** | Keep 0.3 | No | Separate `pre_llm_call` hook bypasses scoring entirely to inject synthesis |
| **Market** | Start 0.5 | Enable `fact_feedback` | Equal competition; user/feedback adjusts trust up/down |
| **Auto-demote** | Start 0.5 | Internal tracking | Track usage; decay unused synthesis automatically |

**Current state:** Hook exists in code/docs but is disabled. Market model is incomplete because retrieval counting is broken. Auto-demote requires retrieval counting to work.

## Trust Stasis

Because `retrieval_count` never increments and `fact_feedback` is never called:
- Trust scores are **static**.
- `update_fact_feedback()` in `store.py` (line 356+) is dead code from the perspective of normal usage.
- The entire `score = relevance * trust_score` formula operates on frozen values.

## Reflect Pipeline Context

Reflect generates synthesis facts at `trust_score = 0.3` with `source >= 0.5` and inherited category. It runs autonomously via cron at 02:00 local time. Synthesis facts are second-class by design: no `fact_feedback`, structural suppression via scoring. They are generative (new inferred claims), not corrective (rescuing missed facts).
