# Entity Extraction Gaps — All-Caps Acronyms

## The Bug: All-Caps Acronyms Never Bind

`_RE_CAPITALIZED` in `store.py`:
```python
_RE_CAPITALIZED = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
```

This requires `[A-Z]` followed by `[a-z]`. It **never matches**:
- `ConditionA` — no lowercase letter follows first capital
- `InsurerC` — same
- `MedicationB` — same
- `LTVP` — same
- `GCP` — same

The result: these entities appear in FTS (full-text search works) but have **zero HRR binding**. `probe("ConditionA")` returns high-confidence noise, not real matches.

## Detection

Run the binding rate check per seed anchor:
```python
anchors = [("ConditionA", seed_fid), ("InsurerC", seed_fid), ("MedicationB", seed_fid), ("parents", seed_fid)]
for name, seed_fid in anchors:
    bound = conn.execute("SELECT COUNT(*) FROM fact_entities fe JOIN entities e ON e.entity_id = fe.entity_id WHERE e.name = ?", (name,)).fetchone()[0]
    total = conn.execute('SELECT COUNT(*) FROM facts WHERE fact_id != ? AND content LIKE ?', (seed_fid, f'%{name}%')).fetchone()[0]
    rate = round(bound / total, 3) if total > 0 else 0.0
    print(f"{name}: {rate} ({bound}/{total})")
```

## The Fix

Add double quotes around the acronym in the fact content:
```python
new = re.sub(r'\bJME\b', '"ConditionA"', old)
new = re.sub(r'\bInsurerC\b', '"InsurerC"', new)
new = re.sub(r'\bMedicationB\b', '"MedicationB"', new)
new = re.sub(r'\bparents\b', '"parents"', new)
```

Then call `fact_store update` with the changed content string per fact. The content delta triggers `_compute_hrr_vector()`.

## Verified Fix (empirical results)

| Anchor | Before | After | Threshold |
|--------|--------|-------|-----------|
| ConditionA | 0.400 (6/15) | 0.933 (14/15) | 0.90 ✅ |
| InsurerC | 0.353 (6/17) | 0.867 (13/15) | 0.85 ✅ |
| MedicationB | 0.636 (7/11) | 0.909 (10/11) | 0.85 ✅ |

## Quotes alone don't guarantee 100% binding

| Anchor | Prior rate | After store growth | Notes |
|--------|------------|-------------|-------|
| ConditionA | 93.3% (14/15) | 82.9% (29/35) | Store grew; entity appears in more facts |
| InsurerC | 86.7% (13/15) | 60.7% (17/28) | Same |
| MedicationB | 90.9% (10/11) | 82.6% (19/23) | Same |

Even properly quoted facts sometimes have zero binding in `fact_entities`. The extraction regex misses contextual patterns.

**Key: `fact_entities` direct query is the only reliable binding check. Content presence is NOT a proxy.**

## Janitor Pass 1 Results + UNIQUE Constraint Hazard

22 facts updated via `fact_store update`. Binding rates after fix:

| Anchor | Before | After | Threshold | Status |
|--------|--------|-------|-----------|--------|
| ConditionA | 0.744 (28/35) | 1.0 (34/34) | 0.90 | ✅ Above threshold |
| parents | 0.750 (20/25) | 0.96 (24/25) | 0.85 | ✅ Above threshold |
| MedicationB | 0.655 (18/28) | 0.893 (25/28) | 0.85 | ✅ Above threshold |
| InsurerC | 0.586 (16/29) | 0.621 (18/29) | 0.85 | ❌ Still below |

**InsurerC residual gaps — false positives from LIKE matching:**
`WHERE content LIKE '%InsurerC%'` matched these non-entity occurrences:
- `#565`: `insurance-insurerc-ci` (kanban tenant — lowercase identifier, not an entity)
- `#577`: `insurerc-smartlink` (policy name — lowercase compound)
- `#454`: `insurerc` only in tags (tags not extracted from content)
- `#488`: `"InsurerC"` properly quoted but not in `fact_entities` — residual binding failure

**UNIQUE constraint hazard:** Facts #646 and #647 shared identical opening text. After quoting, identical content strings caused `UNIQUE constraint failed` on the second `fact_store update` (which calls `remove`+`add` internally). Fix: differentiate content first (append a parenthetical like "(fragment A)"), then update both.

**Lesson:** Verify content uniqueness before bulk `update`. Check `fact_entities` directly rather than inferring binding from content presence.

## Entity Fragmentation + All Anchors at 100%+

**Problem: Entity fragmentation causes bound-to-wrong-entity.**

Facts #573, #574, #375, #430, #575, #582, #576, #548 all had `"InsurerC"` properly quoted in content AND had entity bindings in `fact_entities` — but to `InsurerC ProductF` (entity_id=187), `InsurerC Hospital` (entity_id=192) instead of `InsurerC` (entity_id=105). The LIKE count looked like "unbound" because it counted 29 mentions but only 17 were bound to the canonical `InsurerC` entity. The other 12 were bound to sub-entities.

Root cause: prior write sessions extracted `InsurerC ProductF` (multi-word) as its own entity via `_RE_CAPITALIZED`, creating `entity_id=187`. Later writes that quote `"InsurerC"` bind to entity_id=105 (`InsurerC`). Both co-exist in `fact_entities` for the same fact, but probe/reason uses canonical name matching — so the fact doesn't surface in `probe("InsurerC")` searches.

**Fix:** Re-call `fact_store update` with the same content on each affected fact. The `_compute_hrr_vector` call re-runs `_extract_entities` fresh and properly links to `InsurerC` (entity_id=105). No content change needed — the update call itself is the fix.

**Final binding rates (all 4 anchors at 100%+):**

| Anchor | Rate | Bound/Total | Threshold |
|--------|------|-------------|-----------|
| ConditionA | 1.029 | 35/34 | 0.90 OK |
| parents | 1.040 | 26/25 | 0.85 OK |
| MedicationB | 1.000 | 28/28 | 0.85 OK |
| InsurerC | 1.034 | 30/29 | 0.85 OK |

**MedicationB also had 4 truly unbound facts** (#592, #454, #617, #534) — lowercase `depakote` in content with no quotes. Fixed by adding `"MedicationB"` in content and calling `update`.

**parents had 2 unbound facts** (#545, #541) — content had `"parents"` quoted but `fact_entities` rows were 0. Calling `update` with same content rebuilt the full chain (entity links + HRR vector).

**Key insight:** LIKE-based binding detection produces false positives when sub-entities exist. `fact_entities` direct SQL join is the only reliable check. Content presence of a quoted term does NOT confirm binding.

**UNIQUE constraint deadlock:** #646/#647 both started with identical content "User demands empirical verification...". After quoting Pass 1, updating #646 first triggered `remove`+`add`; the `add` failed because #647 still held the identical content string. Resolution: differentiated #646's content (append disambiguating phrase), called `update`, then restored original and called `update` again. **Pre-check for duplicates is mandatory before any Pass 1 bulk update.**