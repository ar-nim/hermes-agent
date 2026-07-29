# Holographic Bank Corruption — Diagnosis & Repair


**Symptom:** `setting an array element with a sequence. The requested array has
an inhomogeneous shape after 1 dimensions. The detected shape was (N,) + inhomogeneous part.`
**Category affected:** `user_pref` (227 facts at the time)

## The Bug

A subset of facts in one category had `hrr_vector` bytes at a different
dimensionality than the rest of the bank. When `_rebuild_bank` tried to
`hrr.bundle(*vectors)`, numpy rejected the inhomogeneous list.

In the observed incident, three facts (#831, #832, #833) had `hrr_vector` of
**8192 bytes = 1024 floats** while every other fact in the bank had **32768
bytes = 4096 floats** (matching `hrr_dim: 4096` in `~/.hermes/config.yaml`).

```
$ python3 -c "import sqlite3, os; ..."
=== user_pref hrr_vector inspection ===
user_pref: 227 facts, byte_lens={32768: 224, 8192: 3}
OUTLIERS:
  #831 byte_len=8192 (expected 32768)
  #832 byte_len=8192 (expected 32768)
  #833 byte_len=8192 (expected 32768)
```

`8192 * 4 = 32768` — exactly 4×. The 3 outliers were at hrr_dim=1024 (the
source-code default in `store.py:105`), the rest at the configured 4096.

## Why the symptom blocks writes (not just reads)

The error fires from `_rebuild_bank()` at `store.py:498-517`, called by every
write (`add_fact` line 187, `update_fact` line 302, `remove_fact` line 320).
Adding any new fact in the affected category → `_compute_hrr_vector` runs →
`_rebuild_bank` runs → bundle fails on inhomogeneous shapes → write rejected.

So the user-facing symptom is "I can't add a `user_pref` fact" even though the
fault is in a sibling fact's stored vector from days ago.

## Root Cause

All three corrupt facts were:
- `category='user_pref'`
- `trust=0.3`
- `tags LIKE '%reflect-synthesis%'`
- `created_at='2026-05-28 20:09:03'` (same second)

This is the fingerprint of a `holographic-memory-reflect` run that instantiated
`HolographicStore()` without reading `hrr_dim` from `config.yaml`. The
constructor default (`store.py:105: hrr_dim: int = 1024`) won, and every fact
that run wrote got a 1024-dim vector — invisible corruption until a future
write tried to bundle it with a 4096-dim bank.

**This is a real bug in the reflect pipeline.** It is NOT fixed by repairing
the bank — the next reflect run will re-introduce the corruption. The
`holographic-memory-reflect` skill should be patched separately to enforce
reading `hrr_dim` from `config.yaml` before instantiating `HolographicStore()`.

## Detection (re-runnable)

```bash
python3 ~/.hermes/skills/holographic-memory/holographic-memory-janitor/scripts/check_bank_integrity.py
```

The script does per-category byte-length audits and flags outliers:

```python
import sqlite3, os
from collections import Counter
conn = sqlite3.connect(os.environ['HERMES_HOME'] + '/memory_store.db')
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA query_only=ON')

for cat in ('user_pref', 'general', 'tool', 'project'):
    rows = conn.execute(
        "SELECT fact_id, length(hrr_vector) AS byte_len "
        "FROM facts WHERE category = ? AND hrr_vector IS NOT NULL",
        (cat,)
    ).fetchall()
    lens = Counter(r['byte_len'] for r in rows)
    if len(lens) > 1:
        majority = lens.most_common(1)[0][0]
        bad = [r['fact_id'] for r in rows if r['byte_len'] != majority]
        # REPORT
```

## Fix Procedure (the "last update succeeds" pattern)

For each corrupt fact: `fact_store update(fact_id=N, content=<verbatim content>)`.

The store's `update_fact()` at `store.py:242-304` runs in this order:
1. `UPDATE facts SET content = ?, updated_at = CURRENT_TIMESTAMP` (line 279-282)
2. `DELETE FROM fact_entities` + re-extract + re-link (line 287-293, if `content is not None`)
3. `_compute_hrr_vector(fact_id, content)` (line 297, if `content is not None`) — **this commit succeeds and writes a fresh vector at `self.hrr_dim`**
4. `_rebuild_bank(category)` (line 302) — **this may FAIL while ANY sibling vector in the bank is still wrong-dim**

The actual sequence observed:

| Call | `_compute_hrr_vector` result | `_rebuild_bank` result | Why |
|---|---|---|---|
| `update(#831, content)` | ✓ new 32768-byte vector written | ✗ FAIL — #832 + #833 still 8192 | #831 was fixed but bank still inhomogeneous |
| `update(#832, content)` | ✓ new 32768-byte vector written | ✗ FAIL — #833 still 8192 | #832 fixed, only #833 left |
| `update(#833, content)` | ✓ new 32768-byte vector written | ✓ SUCCESS — all 227 vectors now 32768 | Last outlier removed; bank rebuilds cleanly |

**Key insight:** the `_compute_hrr_vector` step commits its write BEFORE
`_rebuild_bank` is attempted. So even when the rebuild fails and `update` returns
an error, the targeted fact's hrr_vector IS already at the correct dim. Errors
from the first N-1 updates are expected and non-fatal. Only the final update
returns success.

This is the **opposite** of what the best-practices pitfalls 27 and 29 say
("update with byte-identical content doesn't re-extract"). Those pitfalls are
outdated: `store.py` has no byte-equality check, and the recompute fires
unconditionally whenever `content is not None`. See the entity-extraction-gaps reference
which already
documented this empirically.

## Verification

After the final `update` succeeds:
- All `hrr_vector` byte lengths in the affected category are uniform
- `memory_banks` row for that category has `dim = self.hrr_dim` (4096)
- A `fact_store probe` against that category returns without raising
- A new `fact_store add` in that category succeeds

## Adjacent Findings (not fixed in this session)

- **Orphan banks in `memory_banks`:** `cat:financial` (1 fact), `cat:health`
  (2 facts) still present. Leftovers from an invalid-category
  migration. Should be removed: `DELETE FROM memory_banks WHERE bank_name IN
  ('cat:financial', 'cat:health')`.
- **30 facts with `hrr_vector IS NULL`** across all 4 valid categories
  (user_pref=18, general=10, tool=1, project=1). Invisible to HRR algebra per
  pitfall #28 but present in `facts`. Fix: `fact_store update` with verbatim
  content for each.
- **Reflect pipeline dim bug** is the actual root cause. Until that's fixed,
  this exact corruption will reappear on every reflect run that doesn't read
  `hrr_dim` from config.

## Prevention

1. Run `check_bank_integrity.py` as part of every janitor pre-flight, BEFORE
   the seed-anchor check — a corrupt bank makes every subsequent probe/add
   fail with a confusing numpy error.
2. Add a startup self-check in `HolographicStore.__init__` that compares
   `self.hrr_dim` against the actual `length(hrr_vector) / 8` of an existing
   fact in each category and warns on mismatch.
3. Patch the reflect pipeline to pass `hrr_dim=int(cfg_get(..., 'hrr_dim',
   default=1024))` explicitly when instantiating `HolographicStore()`.
