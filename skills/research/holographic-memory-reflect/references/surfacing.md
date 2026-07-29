# Surfacing Layer — How Synthesis Reaches the Conversation

## The Three-Layer Architecture

Holographic memory has three distinct operational layers:

| Layer | What it does | Governed by |
|---|---|---|
| **Generate** | Reflect produces higher-order inferred claims | `holographic-memory-reflect` |
| **Store** | Facts written to SQLite via fact_store | `holographic-memory-lite` Pre-Write Checkpoint |
| **Surface** | Synthesis injected into LLM context at inference time | `pre_llm_call` hook (this document) |

Reflect generates synthesis facts. But generation does not guarantee the LLM sees them during conversation. That requires the surfacing layer.

---

## The Surfacing Gap

**Problem observed (May 4, 2026):** Synthesis facts existed in the store (trust 0.3–0.5, tagged `reflect-synthesis`) but were not surfacing during conversation. The BuiltinMemoryProvider's `prefetch()` uses FTS5 keyword matching with:
- Pure keyword overlap between user message and fact content
- Hard cap at 5 results
- `min_trust=0.3`

This means synthesis surfaces only when the user message contains keywords that appear in the synthesis content. For all-lowercase messages or messages with no keyword overlap to synthesis content, retrieval returns empty — even when synthesis is highly relevant to the conversation topic.

**Root cause:** The surfacing mechanism (prefetch) uses retrieval, not inference. It finds facts that match the message. It does not proactively inject facts that are relevant to the message's underlying context.

---

## The Solution: `pre_llm_call` Shell Hook

Hermes fires `pre_llm_call` before every LLM call. The hook receives the raw user message and can return `{"context": "..."}` to inject text directly into the user message slot.

**Implementation:** `$HERMES_HOME/scripts/memory-remind.py`

**Config in `~/.hermes/config.yaml` (or `$HERMES_HOME/config.yaml`):**
```yaml
hooks:
  pre_llm_call:
    - command: "$HERMES_HOME/scripts/memory-remind.py"
      timeout: 8
```

**Wire protocol:**
- stdin: JSON payload with `user_message`, `session_id`, `conversation_history`, `is_first_turn`, `model`, `platform`
- stdout: `{"context": "injected text"}` or `{"context": ""}` for silent no-op

**The script:**
1. **Profile guard (two-layer)** — verifies `active_profile` file exists AND the profile directory actually exists. If either check fails, returns empty. Prevents cross-profile memory leakage.
2. **Entity extraction** — extracts capitalized multi-word phrases and single capitalized words from user message. Falls back to keyword scan (3+ char words) for all-lowercase messages.
3. **Synthesis retrieval** — FTS5 match on entities + direct LIKE scan on synthesis content/tags for lowercase fallback. Queries trust band 0.3–0.55 to capture both synthesis (0.3) and high-trust raw facts (0.5).
4. **Deduplication + ranking** — content deduplication then trust-sort. Returns top 4-5 facts.
5. **Format** — `[synth]` label for trust ≤0.4, `[infer]` for 0.4–0.55. Profile name included in header.

---

## Profile-Guard Implementation (Two-Layer Defense)

```python
def get_verified_profile() -> Optional[str]:
    active_file = HERMES_HOME / "active_profile"
    if not active_file.exists():
        return "default"
    try:
        candidate = active_file.read_text().strip()
    except OSError:
        return None
    if not candidate or candidate == "default":
        return "default"
    # Layer 2: verify directory exists
    profile_dir = HERMES_HOME / "profiles" / candidate
    if not profile_dir.is_dir():
        return None  # Stale pointer — do NOT fallback
    return candidate
```

| Scenario | Result |
|---|---|
| No `active_profile` file | `"default"` |
| File contains valid named profile + dir exists | profile name |
| File contains stale name (no matching dir) | `None` → hook exits silently |
| File unreadable | `None` → hook exits silently |

This is critical for multi-profile setups. Without Layer 2, a stale `active_profile` file pointing to a deleted profile would silently fall back to `default` — potentially surfacing the wrong profile's memory.

---

## Known Bugs Caught During Implementation

**Bug 1: Wrong column name (`id` vs `fact_id`)**

The SQLite schema uses `fact_id` as the primary key column, not `id`. The FTS5 JOIN query initially used `f.id` which silently returned zero rows (no error, just empty results). Confirmed working query:

```sql
SELECT f.fact_id, f.content, f.trust_score, f.category, f.tags
FROM facts f
JOIN facts_fts fts ON f.fact_id = fts.rowid  -- NOT f.id
WHERE facts_fts MATCH ?
```

**Bug 2: All-lowercase messages yield zero entities**

The entity extraction regex `r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b'` only matches capitalized words. Messages like "what do you know about my financial commitments" extract zero entities → synthesis retrieval skipped entirely.

**Fix:** Keyword fallback scans synthesis fact content/tags directly for significant words (3+ chars, stopword-filtered), regardless of capitalization.

---

## Relationship to BuiltinMemoryProvider

The surfacing hook and BuiltinMemoryProvider operate independently:

- **BuiltinMemoryProvider.prefetch()** — runs silently on every turn, FTS5 keyword match, capped at 5 results. Handles general fact retrieval.
- **pre_llm_call hook** — profile-guarded, synthesis-focused, entity-aware. Handles proactive surfacing of reflective synthesis.

Both outputs are injected into the user message slot. They are complementary, not redundant.

---

## Future: What Would Improve Surfacing Further

1. **Entity-level reason() call** — instead of just FTS5 keyword match, run `probe()` on extracted entities to get HRR-bound synthesis. More accurate but slower (requires hermes_tools import or direct retriever access).

2. **Cross-entity synthesis** — when multiple entities are extracted, check synthesis facts that reference multiple of them. These are the highest-value synthesis hits (cross-domain patterns).

3. **Pre-compact hook** — before context compression, extract critical synthesis from facts at risk of being compacted. Currently no hook for this in Hermes.
