# Entity Extraction Diagnostics

## The Entity Extraction Bottleneck

During atomic vs bundled SNR testing on real store data, a critical finding emerged: **entity extraction is the dominant failure mode for probe/retrieve**, not SNR, bundling, or vector dimensions.

### Key Finding

| Metric | Value |
|---|---|
| General facts | 118 |
| Facts with 0 extracted entities | 80 (68%) |
| Facts with 1+ entities | 38 (32%) |
| Mean entities/fact | 0.45 |
| Probe hit rate (#1 correct) | 0% |

Probe scores clustered at ~0.255 (noise floor). All probe scores for correct facts were below scores for wrong facts — **probe retrieval was inverted** on real data.

### Root Cause: Entity Extraction Regex

The store's `_extract_entities()` in `store.py` uses 4 patterns:
1. Title-case multi-word phrases: `\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b`
2. Double-quoted terms: `"([^"]+)"`
3. Single-quoted terms: `'([^']+)'`
4. AKA patterns: `\w+(?:\s+\w+)*\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)`

**Problem:** This misses:
- Lowercase tokens: `"conditiona"`, `"isp"`, `"lr"`, `"smarthub"`, `"joplin"`
- Abbreviations: `"MCC"`, `"JAK"`, `"GTFS"`
- Single-word title-case that appears without context: `"Acme"` without a following lowercase word

**What the regex captures:** Proper nouns that are title-case or quoted in context. In many memory stores, knowledge is encoded as lowercase atoms that never appear in title-case position — these are invisible to the regex.

---

## Correct Entity Extraction Pattern

**The store reads from `fact_entities`, not from re-extraction.**

When auditing what the store actually encoded, query the link table directly:

```python
import sqlite3, os
conn = sqlite3.connect(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/memory_store.db")
conn.row_factory = sqlite3.Row

# Get entities for a specific fact (as store does)
ents = conn.execute("""
    SELECT e.name FROM entities e
    JOIN fact_entities fe ON fe.entity_id = e.entity_id
    WHERE fe.fact_id = ?
""", (fact_id,)).fetchall()
entities = [e['name'] for e in ents]

# NOT this — it's what add_fact does, but _compute_hrr_vector uses fact_entities:
# entities = store._extract_entities(content)
```

The HRR vector is computed via `_compute_hrr_vector(fact_id, content)` which:
1. Reads from `fact_entities` (linked entities, already resolved and deduplicated)
2. Passes those entity names + content to `hrr.encode_fact(content, entities, dim)`
3. Stores the resulting vector

---

## Probe Scoring Algorithm (from retrieval.py)

The `FactRetriever.probe()` method scores facts as:

```
probe_key = bind(encode_atom(entity.lower()), role_entity)
extracted = unbind(bank_vec, probe_key)  # bank-level extraction
for each fact:
    residual = unbind(fact_vec, probe_key)
    score = similarity(residual, content_vec)  # role_content vector
```

The similarity of the residual against the fact's `role_content` vector determines the score. A correct fact should have its entity signal still present in the residual after unbinding — but when entity signal is weak (low extraction density), the residual is dominated by content noise and scores randomly.

---

## SNR vs Reality

| | Atomic (118 facts) | Bundled (24 groups) |
|---|---|---|
| Raw bank SNR | sqrt(4096/118) = 5.89 | sqrt(4096/24) = 13.06 |
| Actual probe signal gap | -0.0098 | -0.0098 |
| Probe hit rate | 0% | 0% |

The raw SNR difference is a 2.2× arithmetic advantage for bundled — but actual probe performance is **identical**. The SNR formula assumes:
1. Entity signals are independent and linearly accumulative
2. Unbind cleanly recovers entity signal
3. Content noise averages out

All three assumptions fail on real data with low entity density. The formula counts signal that isn't actually recoverable.

---

## Migration Preserves Entity Links

Entity links in `fact_entities` are preserved during `fact_store` migration (remove + re-add cycle). The `hrr-dimension-migration` skill handles this correctly. Verified:

- Backup (1024-dim): 93 entities, 136 fact_entity links
- Current (4096-dim): 98 entities, 77 fact_entity links
- Links differ because some facts were added/modified post-migration, and fact IDs changed (old 131 → new 316 for home-infra fact), but entity linking logic was preserved

When auditing migration integrity: compare `fact_entities` row counts, not `entities` table counts alone. The `entities` table can grow (new entities added) even while `fact_entities` shrinks (old links not recreated if facts were removed).

---

## Diagnostic Queries

```python
# Entity density per category
for cat in ['general', 'user_pref', 'tool']:
    total = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE category=? AND hrr_vector IS NOT NULL", (cat,)
    ).fetchone()[0]
    with_ent = conn.execute("""
        SELECT COUNT(DISTINCT fe.fact_id) FROM fact_entities fe
        JOIN facts f ON f.fact_id = fe.fact_id WHERE f.category=?
    """, (cat,)).fetchone()[0]
    print(f"{cat}: {total} total, {with_ent} with entities, {total-with_ent} ({100*(total-with_ent)/total:.0f}%) without")

# Verify probe with known entity
import os
from store import MemoryStore
from retrieval import FactRetriever
store = MemoryStore(db_path=os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")) + "/memory_store.db", hrr_dim=4096)
retriever = FactRetriever(store, hrr_dim=4096)
results = retriever.probe("Acme", category='general', limit=5)
for r in results:
    print(f"fid={r['fact_id']} score={r['score']:.4f} | {r['content'][:60]}")

# Test entity linking for a specific fact
fid = 316  # home-infra DNS fact
ents = conn.execute("""
    SELECT e.name FROM entities e
    JOIN fact_entities fe ON fe.entity_id = e.entity_id
    WHERE fe.fact_id = ?
""", (fid,)).fetchall()
print(f"Fact {fid} entities: {[e['name'] for e in ents]}")
```
