# HRR Architecture Reference

## Module Location
```
$HERMES_HOME/plugins/memory/holographic/
├── holographic.py   # Core HRR: encode_atom, bind, unbind, bundle, similarity, encode_fact
├── store.py         # MemoryStore: SQLite-backed fact store with HRR vector column
├── retrieval.py      # Compositional retrieval using HRR algebra
└── plugin.yaml
```

## HRR Implementation (holographic.py)

**Type:** Phase-encoded Holographic Reduced Representations

**Key functions:**
- `encode_atom(word, dim=1024)` — deterministic phase vector via SHA-256 counter blocks. Cross-platform reproducible.
- `bind(a, b)` — circular convolution = element-wise phase addition
- `unbind(memory, key)` — circular correlation = element-wise phase subtraction
- `bundle(*vectors)` — superposition via circular mean of complex exponentials
- `similarity(a, b)` — phase cosine similarity, range [-1, 1]
- `encode_fact(content, entities, dim)` — structured encoding: content bound to ROLE_CONTENT, each entity bound to ROLE_ENTITY, all bundled
- `encode_text(text, dim)` — bag-of-words: bundle of atom vectors per token

**Phase encoding:** angles in [0, 2π), float64. Numerically stable vs. complex-number HRRs. Maps cleanly to cosine similarity.

**SNR:** `sqrt(dim / n_items)`. Falls below 2.0 when `n_items > dim/4`. At dim=1024, capacity ~256 items per bank before retrieval degrades.

## Database (store.py)

**Path:** `$HERMES_HOME/memory_store.db` (resolved via `get_hermes_home()`)

**Schema:**
```sql
CREATE TABLE facts (
    fact_id         INTEGER PRIMARY KEY,
    content         TEXT UNIQUE,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP,
    hrr_vector      BLOB         -- serialized float64 phases, 8 KB at dim=1024
);

CREATE TABLE memory_banks (
    bank_id    INTEGER PRIMARY KEY,
    bank_name  TEXT,             -- e.g. "cat:general", "cat:user_pref"
    vector     BLOB NOT NULL,    -- bundle of all fact HRR vectors in category
    dim        INTEGER,          -- 1024
    fact_count INTEGER
);
```

**Key behavior:** `_hrr_available = hrr._HAS_NUMPY` is evaluated at the time `holographic.py` is first imported. If numpy was absent at that moment, `_HAS_NUMPY = False` and HRR computation is permanently disabled for that process.

## Operational Dependency: NumPy

NumPy is required for all HRR operations. Install via:
```
pip install numpy
```

**Restart required after install:** `_HAS_NUMPY` is cached at module import time. A running agent won't pick up a newly installed numpy until restarted.

**Verify:**
```python
python3 -c "import numpy as np; print(np.__version__)"
```

## Retrieval Pipeline
1. FTS5 full-text search on content + tags (always fires for keyword queries)
2. Jaccard overlap on tokenized content + tags
3. HRR algebra (only when `probe(entity)` fires with a quoted entity that was extracted)
4. Category HRR banks (only when `probe(entity, category="...")` is called explicitly)
