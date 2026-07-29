# Holographic Memory: SNR, Capacity & Trust Formulas

## SNR Capacity (per category bank)

```
SNR = sqrt(hrr_dim / fact_count)
```

| hrr_dim | 512 facts | 1024 facts | 2048 facts |
|---------|-----------|-------------|-------------|
| 1024    | 1.41      | 1.00        | 0.70        |
| 2048    | 2.00      | 1.41        | 1.00        |
| 4096    | 2.83      | 2.00        | 1.41        |

**Decision thresholds:**
- SNR > 2.5 → keep current hrr_dim
- SNR 1.5–2.5 → consider 2048
- SNR < 1.5 → switch to 2048 or 4096

**SNR rule:** Each category bank is independently limited by `sqrt(hrr_dim / count)`. At 4096 dims, a category can hold ~1024 high-fidelity facts before SNR degrades to 2.0. At 1024 dims, same category hits 1.0 at 1024 facts.

## Trust Asymmetry (2:1 penalty ratio)

```python
HELPFUL_DELTA   = +0.05  # store.py:79
UNHELPFUL_DELTA = -0.10  # store.py:80
```

**3-strike buffer** (default trust 0.5, min_trust 0.3):

| Action | Result |
|--------|--------|
| 1st unhelpful | 0.40 (still visible) |
| 2nd unhelpful | 0.30 (on threshold, still visible) |
| 3rd unhelpful | 0.20 ← **hidden** |

Recovery: 2 helpful votes needed per -0.10 drop.

**Append-only deprecation is a soft-delete cascade risk.** If a deprecated fact sits at trust=0.30 (on threshold), one `feedback(unhelpful)` drops it to 0.20. Three strikes total from default trust to invisible.

## Temporal Decay (only when enabled)

```python
decay = 0.5^(age_days / half_life_days)  # retrieval.py:591
score = relevance * trust_score * decay
```

**`temporal_decay_half_life` defaults to 0 (disabled).** Enable only in config.yaml. Decay is NOT reset by `feedback` — only by `update`.

**Decay table** (half_life=90d, trust=0.5):

| Age | Decay mult | Effective score |
|-----|-----------|----------------|
| 30d | 0.79      | 0.39           |
| 90d | 0.50      | **0.25 ← below 0.3** |
| 180d| 0.25      | 0.12           |
| 365d| 0.06      | 0.03           |

## Update Patterns

| Pattern | When to use | Trust effect |
|---------|-------------|--------------|
| `update` (Pattern A) | Metadata-only: tags, category, quote fixes | Preserved in-place |
| `feedback`+`add` (Pattern B) | Content change with historical reference value | New fact at 0.5 |
| `remove`+`add` (Pattern C) | Wholly obsolete facts | New fact at 0.5 |

**UNIQUE constraint trap:** `add` on duplicate content silently returns existing fact_id (store.py:~165 `IntegrityError` catch). Never use `add` to update metadata — always use `update`.

## Migration: `rebuild_all_vectors(dim)`

```python
def rebuild_all_vectors(self, dim: int | None = None) -> int:
    """Recompute all HRR vectors + banks from text. For recovery/migration.
    Returns the number of facts processed."""
```

Found in store.py. Preferred migration path for hrr_dim changes — processes all facts, rebuilds every category bank in one pass. Requires fact_store session (not available in cron, which uses `skip_memory: true`).

**Migration procedure:**
1. Backup: two copies of `memory_store.db`
2. Export: JSON dump of all facts
3. Change `hrr_dim` in config.yaml
4. Call `rebuild_all_vectors(dim=4096)` in interactive session
5. Verify: `SELECT LENGTH(hrr_vector) FROM facts LIMIT 1` → 32768 bytes
