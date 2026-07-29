# `execute_code` Environment Isolation

Each `execute_code` call runs in a **fresh Python namespace**. Variables and imports from prior calls do not persist.

## Implication for Reflect

`reflect_pipeline.py` is called via `execute_code` at multiple points (Steps 0, 2, 3d-3f). Every call must independently import its dependencies:

```python
# Wrong — sys not defined in fresh namespace
conn = get_db_conn()

# Correct — re-import everything each call
import sys, os
sys.path.insert(0, ...)
from reflect_pipeline import get_db_conn
conn = get_db_conn()
```

## Verified Working Pattern (Reflect Pipeline)

```python
import sys, os, sqlite3, re
from datetime import datetime, timezone

hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
skill_dir = os.path.join(hermes_home, "skills/holographic-memory/holographic-memory-reflect")
sys.path.insert(0, skill_dir)

from reflect_pipeline import get_db_conn, compute_entity_stats, classify_entity_temporal

# Now use the functions
conn = get_db_conn()
# ...
```

## Pre-Write Synthesis Quoting Check

Before writing synthesis facts, verify all single-word capitalized entities are double-quoted:

```python
import re

def verify_entity_quoting(content, entities_to_check):
    """Return list of unquoted entities found in content."""
    unquoted = []
    for entity in entities_to_check:
        if entity in content:
            if not re.search(rf'"({re.escape(entity)})"', content):
                unquoted.append(entity)
    return unquoted

# Usage
SINGLE_WORD_CAPITALS = ["User", "Kubernetes", "CityX", "EP", "ConditionA", "MedicationB",
                         "CityBus", "Telegram", "NationalWeatherAPI", "CityRail", "InsurerC", "LTVP",
                         "GCP", "CountryY", "EmployerE"]

unquoted = verify_entity_quoting(synthesis_content, SINGLE_WORD_CAPITALS)
if unquoted:
    raise ValueError(f"Unquoted entities: {unquoted}")
```

**Empirical basis**: Synthesis facts #592, #454, #534 were written with unquoted `MedicationB`/`ConditionA` and required janitor Pass 1 to fix. Prevention is at generation time — the reflect pipeline does not call `fact_entities` at write-time.
