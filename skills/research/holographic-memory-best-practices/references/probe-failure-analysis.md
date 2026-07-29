# probe() Failure: Algorithmic Root Cause Analysis

**Method:** Source code analysis + empirical testing + 3-expert consultation

---

## Executive Summary

`probe()` is unreliable for single-word entities regardless of dimensionality. D=4096 (SNR=3.06) confirmed. The failure is NOT dimensional — it is algorithmic and scales with corpus size N, not dimension D.

Root cause: two independent failure modes in the probe() scoring algorithm.

---

## Two Independent Failure Modes

### 1. Bank Path: SNR ≈ 0.019 (Noise Dominates)

```
bank_vec = normalize(fact_1 + fact_2 + ... + fact_N)  # N = 335
extracted = hrr.unbind(bank_vec, probe_key)

For 2-3 facts containing "EntityA":
  unbind(fact_j, probe_key) ≈ role_entity + noise

For the other 332 facts:
  unbind(fact_k, probe_key) ≈ noise_only

extracted ≈ 2.5 × role_entity + 335 × noise_term
```

Signal power: |2.5 × role_entity|² ≈ 6.25
Noise power: N terms, each with variance ≈ 1 (normalized vectors in D-dim)
**SNR of extracted vector: 6.25 / 335 ≈ 0.019** — signal drowns in noise.

Noise stddev = sqrt(335/4096) ≈ 0.286
Signal magnitude = 0.25-0.5

**Noise stddev is comparable to or larger than signal. Rankings are dominated by random noise.** This is NOT a dimensionality problem — it scales with N, not D.

### 2. Individual Path: Orthogonal Role Atoms

```python
residual = hrr.unbind(fact_vec, probe_key)  # ≈ role_entity
content_vec = hrr.bind(hrr.encode_text(content), role_content)  # role_content atom
sim = hrr.similarity(residual, content_vec)  # role_entity vs role_content
```

`role_entity` and `role_content` are quasi-orthogonal HRR atoms.
Expected similarity ≈ 0.

The code compares the residual to `content_vec` (bound to `role_content`) instead of to `role_entity`. This is the wrong comparison. The correct comparison would be `similarity(residual, role_entity)`.

**Expected score: noise. The ranking is effectively random.**

---

## Verified Empirical Results

| Test | probe() result | search() result |
|---|---|---|
| `probe("EntityA")` | ConditionA protocol #1 (0.305), fact 631 #3 (0.301) | fact 631 #2 (correct) |
| `probe("ring")` | ConditionA protocol #1 | Correct via FTS5 |
| `probe("PersonA")` | ConditionA protocol #1 | Correct via FTS5 |

Gap: 0.004 (within noise). **The correct fact (631) ranks only 0.004 above a wrong generic fact — essentially random.**

After quoting fix (entity binding confirmed correct via SQL):
- Fact 631 has `EntityA` in fact_entities ✓
- Fact 631 has `PersonA` in fact_entities ✓
- **Still fails.** Entity binding is correct. The scoring algorithm is broken.

---

## search() Score Formula (Verified)

```
relevance = 0.4 × fts_score + 0.3 × jaccard + 0.3 × hrr_sim
score = relevance × trust_score
```

FTS5 carries 40% weight and dominates when keywords align. `search()` is deterministic — keyword match has effectively infinite SNR.

---

## Practical Rules for Reflect

1. **Single-word entities: use `search()` exclusively** — no exceptions
2. **Multi-word entities (10+ facts): `probe()` may work** — verify with cascade fallback
3. **The cascade: `probe(entity)` → if wrong result (ConditionA as #1 for event-specific entity) → fall back to `search()`**
4. **The automatic proactive path uses `search()`, not `probe()`** — confirmed in `get_relevant_memories()` source code

---

## What Would Fix probe()

The algorithmic fixes needed (not implemented):
- Individual path: compare `residual` to `role_entity`, not `content_vec`
- Bank path: either (a) abandon superposition and score individually, or (b) use a different scoring metric that is robust to noise

**No configuration parameter (min_trust, limit, hrr_dim) fixes this.** It is an algorithm design problem.

---

## Expert Sources

- Expert 1 (VSA mathematics): confirmed bank path SNR problem, orthogonal atom issue, recommended abandoning probe() for single-word
- Expert 2 (retrieval.py code): confirmed score formula, temporal recency absent from probe(), content-context sensitivity as secondary driver
- Expert 3 (source code precise): confirmed bank path N-scaling, orthogonal role atoms, algorithmic root cause, D=4096 SNR analysis

---

## Related Pitfalls in best-practices SKILL.md

- Pitfall 22: probe() fails for single-word proper nouns — algorithmic root cause (this document)
- Pitfall 26: atomic facts failed retrieval — entity binding failure is the real problem
- Pitfall 27: update with identical content does NOT re-extract entities
- Pitfall 28: empty HRR vector = invisible to reflect pipeline