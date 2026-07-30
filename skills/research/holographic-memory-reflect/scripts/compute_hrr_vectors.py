#!/usr/bin/env python3
"""compute_hrr_vectors.py — standalone HRR vector computation for reflect pipeline.

Usage:
    python3 compute_hrr_vectors.py [fact_id1] [fact_id2] ...
    python3 compute_hrr_vectors.py --all-null

Computes HRR vectors for facts with NULL hrr_vector.
Without args: computes for ALL facts with NULL hrr_vector.
With fact_id args: computes for those specific facts.

Uses MemoryStore (shared connection + plugin's db_path resolution via
get_hermes_home()). Does NOT use os.environ["HERMES_HOME"] for DB path.
"""
import sys
import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_AGENT_DIR = HERMES_HOME / "hermes-agent"
_PLUGIN_DIR = _AGENT_DIR / "plugins" / "memory" / "holographic"
for _p in [str(_PLUGIN_DIR), str(_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import holographic as hrr
from store import MemoryStore


def compute_for_fact_id(store: MemoryStore, fact_id: int) -> bool:
    """Compute and store HRR vector for a single fact. Returns True if computed."""
    with store._lock:
        row = store._conn.execute(
            "SELECT content FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        if not row:
            print(f"  SKIP {fact_id}: fact not found")
            return False

        content = row[0]

        # Get entities linked to this fact
        entity_rows = store._conn.execute(
            "SELECT e.name FROM entities e "
            "JOIN fact_entities fe ON fe.entity_id = e.entity_id "
            "WHERE fe.fact_id = ?",
            (fact_id,),
        ).fetchall()
        entities = [r[0] for r in entity_rows]

        # Compute HRR vector at the store's configured dimension
        vector = hrr.encode_fact(content, entities, store.hrr_dim)
        store._conn.execute(
            "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
            (hrr.phases_to_bytes(vector), fact_id),
        )
    print(f"  OK {fact_id}: {len(entities)} entities, {len(vector)} dims")
    return True


def main():
    store = MemoryStore()

    if len(sys.argv) > 1 and sys.argv[1] == "--all-null":
        with store._lock:
            rows = store._conn.execute(
                "SELECT fact_id FROM facts WHERE hrr_vector IS NULL ORDER BY fact_id"
            ).fetchall()
        fact_ids = [r[0] for r in rows]
        print(f"Found {len(fact_ids)} facts with NULL HRR vector")
    elif len(sys.argv) > 1:
        fact_ids = [int(x) for x in sys.argv[1:]]
        print(f"Computing HRR for {len(fact_ids)} specified facts")
    else:
        print("Usage: compute_hrr_vectors.py [fact_id1] ... | --all-null")
        store.close()
        sys.exit(1)

    computed = 0
    for fid in fact_ids:
        if compute_for_fact_id(store, fid):
            computed += 1

    store._conn.commit()
    store.close()
    print(f"Done: {computed}/{len(fact_ids)} vectors computed")


if __name__ == "__main__":
    main()
