# Entity Binding Rate Interpretation

## What the Rate Means

```
rate = bound_facts / fts_mentions
```

- **bound_facts**: facts linked to this entity in `fact_entities` (HRR-indexed, probe-reachable)
- **fts_mentions**: facts containing this entity name in content (FTS5-indexed, keyword-searchable)

A rate of 1.0 = every fact mentioning the entity is also entity-bound.
A rate of 0.5 = half the facts mentioning the entity are NOT bound — probe() misses them.

## Thresholds

| Rate | Status | Action |
|------|--------|--------|
| ≥ 0.85 | OK | No action needed |
| 0.70–0.85 | WARNING | Investigate unbound facts; consider bulk update |
| < 0.70 | CRITICAL | Significant binding gap; probe() retrieval degraded |

## Stop-Word Contamination

Common English words ("The", "May", "June") can appear as entities with extremely low
binding rates — not because entity extraction failed, but because the word appears as
a normal token in hundreds of facts while being double-quoted (and thus extracted) in
only a handful. Example: "The" has 304 FTS mentions but only 6 entity bindings (rate 0.02).

**These are noise, not signal.** A rate of 0.02 for "The" does not mean entity extraction
is broken — it means "The" is a stop word that shouldn't be an entity at all.

**Diagnostic rule:** When reviewing binding rates, skip entities where:
- The name is a common English stop word (the, a, an, is, in, on, may, jun, etc.)
- FTS mentions > 50 but bound count < 10
- The rate is below 0.10

These entities should be flagged for removal from the entity table, not for binding fixes.

**Root cause:** Fact content containing double-quoted common words (e.g., a sentence like
`content='"The" protocol requires...'`) triggers `_RE_DOUBLE_QUOTE` extraction. The word
gets bound as an entity despite being semantically meaningless.

**Fix:** During janitor cleanup, delete stop-word entities from the `entities` table and
rebuild `fact_entities` links. This is a data quality issue, not an extraction bug.

## Why Rates Are Low

The dominant cause is **unquoted single-word proper nouns** in fact content.

The entity extraction regex `_RE_CAPITALIZED` requires multi-word title-case phrases
(e.g., `TransitLine`). Single-word terms like `CityX`, `InsurerD`, `Partner`
fall into a permanent gap — they are NOT auto-extracted.

**Fix:** Double-quote the entity in content: `"CityX"`, `"InsurerD"`, `"Partner"`.

### Secondary causes

1. Entity appears in a parenthetical or list without being the primary subject
2. Content has special characters (parentheses, slashes, hyphens) near the entity
3. Entity name is a substring of a longer word (use word-boundary regex to avoid false matches)

## Bulk Fix Procedure

For each unbound fact containing the target entity:

1. Read current content via `fact_store(action='probe', entity=<name>)` or `fact_store(action='search', query=<name>)`
2. Verify entity is NOT quoted in content
3. Call `fact_store(action='update', fact_id=N, content=<new_content_with_quotes>)` — this triggers `_extract_entities()` + HRR recompute
4. Verify fix: `fact_store(action='probe', entity=<name>)` should now return the updated fact

**Critical:** `update` with byte-identical content is a no-op (Pitfall 14). The content string MUST change to trigger re-extraction. Adding or moving quotes changes character positions — sufficient to trigger.

## FTS Fallback

Even with low binding rates, `fact_store(action='search')` finds unbound facts via FTS5.
The binding gap affects `probe()` and `reason()` (HRR-based retrieval), not keyword search.

**Practical impact:** If the user asks "what do you know about X?" and the agent uses
`probe(X)`, unbound facts are invisible. If the agent uses `search(X)`, they surface fine.

## Cron Check Usage

```bash
# Check default key entities
python3 $HERMES_HOME/.hermes/skills/holographic-memory/holographic-memory-janitor/scripts/check_entity_binding_rates.py

# Check specific entities
python3 $HERMES_HOME/.hermes/skills/holographic-memory/holographic-memory-janitor/scripts/check_entity_binding_rates.py User ConditionA CityX
```

Exit code 0 = all healthy, exit code 1 = at least one WARNING or CRITICAL.
