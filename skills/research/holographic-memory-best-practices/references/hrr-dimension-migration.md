---
name: hrr-dimension-migration
description: >-
  TRIGGER: When the user asks to change hrr_dim in config (e.g. 1024 to 4096), or when
  SNR calculation warrants an upgrade. Safely migrates the holographic memory store from
  one HRR dimension to another by regenerating all fact vectors at the new dimension.
  Execute only after user reviews and approves the plan.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [holographic, memory, migration, hrr, fact-store]
    related_skills: [holographic-memory-best-practices, holographic-memory-janitor]
---

# HRR Dimension Migration Skill

## Overview

Migrates the holographic memory store to a new `hrr_dim` by regenerating all fact vectors at the new dimension. The procedure is safe, incremental, and verified at every step. Changing `config.yaml` alone does NOT regenerate existing vectors — a full remove+re-add cycle via fact_store is required.

The core constraint: existing facts keep their old-dimension vectors after a config change. A clean migration requires removing all facts, changing config, then re-adding everything.

## When to Use

- User asks to change `hrr_dim` in config (e.g. 1024 → 2048 → 4096)
- SNR calculation warrants an upgrade:
  - `sqrt(1024 / count)` > 2.5 → keep current dim
  - `sqrt(1024 / count)` 1.5–2.5 → consider doubling
  - `sqrt(1024 / count)` < 1.5 → switch to 2048 or 4096

## Prerequisites

- Hermes Agent running with `fact_store` tool available
- Write access to `$HERMES_HOME`
- At least 2x free disk space for the DB backup
- All migration steps run in a single session (cron context has no memory access)

## Step-by-Step

### 0. Confirm current state

```bash
# Check current hrr_dim in config
grep -r "hrr_dim" $HERMES_HOME/

# Verify DB path and row count
sqlite3 $HERMES_HOME/memory_store.db "SELECT COUNT(*) FROM facts;"

# Check vector size (1024 dims = 8192 bytes float64)
sqlite3 $HERMES_HOME/memory_store.db "SELECT LENGTH(hrr_vector) FROM facts LIMIT 1;"
```

### 1. Backup (mandatory — two copies)

```bash
# Primary backup: SQLite VACUUM INTO (transactionally consistent)
sqlite3 $HERMES_HOME/memory_store.db \
  "VACUUM INTO '/path/to/backup/memory_store.backup.v1.db'"

# Secondary backup: plain copy
cp $HERMES_HOME/memory_store.db /path/to/backup/memory_store.copy.v1.db

# Verify both backups exist
ls -la /path/to/backup/memory_store.*
```

**Two backups before ANY write.** `VACUUM INTO` is transactionally consistent. Copy is a second integrity layer.

### 2. Export all facts

```python
import json, sqlite3, os

HERMES_HOME = os.environ.get('HERMES_HOME', '~/.hermes')
DB = os.path.join(HERMES_HOME, 'memory_store.db')

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

facts = conn.execute("""
    SELECT fact_id, content, category, tags, trust_score,
           retrieval_count, helpful_count, created_at, updated_at
    FROM facts ORDER BY fact_id
""").fetchall()

export = [dict(r) for r in facts]

with open('/path/to/backup/facts_export.json', 'w') as f:
    json.dump(export, f, indent=2, default=str)

print(f"Exported {len(export)} facts")
print(f"Categories: {conn.execute('SELECT category, COUNT(*) FROM facts GROUP BY category').fetchall()}")
print(f"Total entities: {conn.execute('SELECT COUNT(*) FROM entities').fetchone()[0]}")
```

Also export memory_banks:
```python
banks = conn.execute("SELECT * FROM memory_banks").fetchall()
with open('/path/to/backup/memory_banks_export.json', 'w') as f:
    json.dump([dict(r) for r in banks], f, indent=2, default=str)
```

### 3. Change config

Update `hrr_dim` in config.yaml — this only affects future facts added after the change.

### 4. Remove + Re-Add via fact_store

Remove facts in batches of 20, then re-add them. The fact_store tool regenerates HRR vectors at the new `hrr_dim` automatically on add.

```python
import json, time

with open('/path/to/backup/facts_export.json') as f:
    facts = json.load(f)

# Remove in batches
for i in range(0, len(facts), 20):
    batch = facts[i:i+20]
    for fact in batch:
        fact_store(action='remove', fact_id=fact['fact_id'])
    print(f"Removed batch {i//20 + 1} ({len(batch)} facts)")
    time.sleep(0.5)

# Re-add in same batch rhythm
for i in range(0, len(facts), 20):
    batch = facts[i:i+20]
    for fact in batch:
        result = fact_store(
            action='add',
            content=fact['content'],
            category=fact['category'],
            tags=fact['tags']
        )
    print(f"Re-added batch {i//20 + 1} ({len(batch)} facts)")
    time.sleep(0.5)
```

> **Note on fact_id**: Removed facts get new fact_ids on re-add. The old→new mapping is NOT preserved. If entity links matter, verify entity extraction after migration.

Also update `memory_banks.dim`:
```python
conn.execute("UPDATE memory_banks SET dim = <new_dim>")
conn.commit()
```

### 5. Verify

1. **Count**: Total facts should match pre-migration count
2. **Content**: Spot-check 5 random facts — content should be identical
3. **Vector size**: `SELECT LENGTH(hrr_vector) FROM facts LIMIT 5` — should be `<new_dim> * 8` bytes
4. **memory_banks.dim**: Should match new `hrr_dim`
5. **Entity links**: `SELECT COUNT(*) FROM fact_entities` should match pre-migration count
6. **Retrieval test**: `fact_store(action='search', query='...')` should return results

### 6. Restore if verification fails

```bash
# Stop Hermes first
# Restore from backup
cp /path/to/backup/memory_store.backup.v1.db $HERMES_HOME/memory_store.db
# Revert config hrr_dim to original
# Restart Hermes
```

---

## HRR Vector Size Reference

| Dimensions | float64 bytes | Notes |
|---|---|---|
| 256 | 2048 | Very small |
| 512 | 4096 | Small |
| 1024 | 8192 | Default |
| 2048 | 16384 | 2x default |
| 4096 | 32768 | 4x default |

## SNR Calculation

`SNR ≈ √(hrr_dim / facts_per_bank)`

At 4096 dims with 170 facts across 4 banks (~42 per bank): SNR ≈ √(4096/42) ≈ 9.9. Even with all 170 in one bank: SNR ≈ √(4096/170) ≈ 4.9.

## Common Pitfalls

1. **Changing config without migrating** — existing vectors stay at old dim, new facts get new dim → inconsistent store
2. **Not vacuuming before backup** — `.backup` without `VACUUM` can include uncommitted writes
3. **Forgetting to update memory_banks.dim** — the bank vectors are still at old dim until updated
4. **Batching removes without re-adding** — empties the store temporarily, increases downtime risk
5. **Not stopping Hermes before restore** — concurrent writes during restore corrupts the DB

## Verification Checklist

- [ ] Current hrr_dim and fact count confirmed before any writes
- [ ] Two backups created (VACUUM INTO + plain copy) and verified
- [ ] All facts exported to JSON before any destructive steps
- [ ] Config hrr_dim updated in config.yaml
- [ ] All facts removed via fact_store in batches
- [ ] All facts re-added via fact_store in same batch rhythm
- [ ] memory_banks.dim updated to match new hrr_dim
- [ ] Verification queries run: count, content spot-check, vector size, entity links
- [ ] If verification fails: restore from backup completed before restarting Hermes
