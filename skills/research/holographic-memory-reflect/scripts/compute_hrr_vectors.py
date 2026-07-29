#!/usr/bin/env python3
"""compute_hrr_vectors.py — standalone HRR vector computation for reflect pipeline.

Usage:
    python3 compute_hrr_vectors.py [fact_id1] [fact_id2] ...
    python3 compute_hrr_vectors.py --all-null

Computes HRR vectors for facts with NULL hrr_vector.
Without args: computes for ALL facts with NULL hrr_vector.
With fact_id args: computes for those specific facts.

Designed to run in cron context (no fact_store tool needed).
"""
import sys
import os
import sqlite3

# Use HERMES_HOME env var (reliable in cron) — falls back to ~/.hermes
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

# Add the plugin directory to path so we can import holographic
PLUGIN_DIR = os.path.join(
    HERMES_HOME,
    "hermes-agent", "plugins", "memory", "holographic"
)
sys.path.insert(0, PLUGIN_DIR)

import holographic as hrr

DB_PATH = os.path.join(HERMES_HOME, "memory_store.db")
HRR_DIM = 4096  # matches store.py default


def compute_for_fact_id(conn, fact_id: int) -> bool:
    """Compute and store HRR vector for a single fact. Returns True if computed."""
    row = conn.execute(
        "SELECT content FROM facts WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    if not row:
        print(f"  SKIP {fact_id}: fact not found")
        return False

    content = row[0]

    # Get entities linked to this fact
    entity_rows = conn.execute(
        """
        SELECT e.name FROM entities e
        JOIN fact_entities fe ON fe.entity_id = e.entity_id
        WHERE fe.fact_id = ?
        """,
        (fact_id,),
    ).fetchall()
    entities = [r[0] for r in entity_rows]

    # Compute HRR vector
    vector = hrr.encode_fact(content, entities, HRR_DIM)
    conn.execute(
        "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
        (hrr.phases_to_bytes(vector), fact_id),
    )
    print(f"  OK {fact_id}: {len(entities)} entities, {len(vector)} dims")
    return True


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if len(sys.argv) > 1 and sys.argv[1] == "--all-null":
        # Find all facts with NULL HRR vector
        rows = conn.execute(
            "SELECT fact_id FROM facts WHERE hrr_vector IS NULL ORDER BY fact_id"
        ).fetchall()
        fact_ids = [r[0] for r in rows]
        print(f"Found {len(fact_ids)} facts with NULL HRR vector")
    elif len(sys.argv) > 1:
        # Specific fact IDs
        fact_ids = [int(x) for x in sys.argv[1:]]
        print(f"Computing HRR for {len(fact_ids)} specified facts")
    else:
        print("Usage: compute_hrr_vectors.py [fact_id1] ... | --all-null")
        sys.exit(1)

    computed = 0
    for fid in fact_ids:
        if compute_for_fact_id(conn, fid):
            computed += 1

    conn.commit()
    conn.close()
    print(f"Done: {computed}/{len(fact_ids)} vectors computed")


if __name__ == "__main__":
    main()
