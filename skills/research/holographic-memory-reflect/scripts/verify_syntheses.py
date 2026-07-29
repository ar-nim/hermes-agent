#!/usr/bin/env python3
"""verify_syntheses.py — verify newly written synthesis facts.

Usage: python3 scripts/verify_syntheses.py <fact_id1> <fact_id2> ...

Checks:
1. Fact exists
2. trust_score = 0.3
3. category in {user_pref, project, tool, general}
4. tags contain required fields
5. hrr_vector IS NOT NULL
6. entity bindings exist
"""
import sqlite3
import os
import sys

def verify(fact_ids: list) -> bool:
    """Verify synthesis facts. Returns True if all checks pass."""
    db_path = os.path.join(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")), "memory_store.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    all_ok = True
    for fid in fact_ids:
        cur.execute(
            "SELECT fact_id, category, trust_score, tags, hrr_vector, content "
            "FROM facts WHERE fact_id = ?",
            (fid,)
        )
        row = cur.fetchone()
        if not row:
            print(f"FAIL: Fact {fid} NOT FOUND")
            all_ok = False
            continue
        
        fid, cat, trust, tags, hrr, content = row
        print(f"Fact {fid}:")
        
        # Check trust_score
        if trust != 0.3:
            print(f"  FAIL: trust_score = {trust}, expected 0.3")
            all_ok = False
        else:
            print(f"  OK: trust_score = 0.3")
        
        # Check category
        valid_categories = {"user_pref", "project", "tool", "general"}
        if cat not in valid_categories:
            print(f"  FAIL: category = '{cat}', must be one of {valid_categories}")
            all_ok = False
        else:
            print(f"  OK: category = '{cat}'")
        
        # Check tags
        required_tags = ["status:current", "type:synthesis", "components:", "reflect-synthesis"]
        missing = [t for t in required_tags if t not in tags]
        if missing:
            print(f"  FAIL: tags missing required fields: {missing}")
            all_ok = False
        else:
            print(f"  OK: tags contain all required fields")
        
        # Check HRR vector
        if hrr is None:
            print(f"  FAIL: hrr_vector is NULL")
            all_ok = False
        else:
            print(f"  OK: hrr_vector is NOT NULL")
        
        # Check entity bindings
        cur.execute("SELECT COUNT(*) FROM fact_entities WHERE fact_id = ?", (fid,))
        count = cur.fetchone()[0]
        if count == 0:
            print(f"  FAIL: zero entity bindings")
            all_ok = False
        else:
            print(f"  OK: {count} entity bindings")
        
        print()
    
    conn.close()
    return all_ok

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 verify_syntheses.py <fact_id1> <fact_id2> ...")
        sys.exit(1)
    
    fact_ids = [int(x) for x in sys.argv[1:]]
    ok = verify(fact_ids)
    sys.exit(0 if ok else 1)
