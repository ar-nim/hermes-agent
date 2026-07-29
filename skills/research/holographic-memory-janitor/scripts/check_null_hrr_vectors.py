#!/usr/bin/env python3
"""
check_null_hrr_vectors.py — pre-flight check for facts with NULL hrr_vector.

Companion to check_bank_integrity.py. That script detects WRONG-DIM vectors
(8192 bytes when config says 4096). This script detects the SILENT-INVISIBLE
case: facts with hrr_vector IS NULL, which the gateway's _rebuild_bank()
silently filters out (see store.py:506: WHERE hrr_vector IS NOT NULL).

A NULL hrr_vector means the fact is invisible to probe(), reason(), and the
reflect pipeline's entity-grounded expansion, even with high trust. No error
is raised — the bank rebuilds cleanly because the NULL facts are just skipped.
Symptoms: a category shows in memory_banks with fact_count=X, but the same
category in facts shows X + (number of null vectors). Probe() returns no
results for entities that should hit those facts.

The fix is the same as for the wrong-dim case: fact_store update with the
fact's current verbatim content recomputes the vector at the configured
hrr_dim. See SKILL.md Pass 0 / bank-corruption-diagnosis references.

Exit codes:
  0 — no NULL vectors
  1 — one or more NULL vectors found
"""
import os
import sqlite3
import sys

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
DB_PATH = os.path.join(HERMES_HOME, "memory_store.db")

CATEGORIES = ("user_pref", "general", "tool", "project")

# Mirror the bind path of memory_banks for comparison
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

total_null = 0
any_null = False
print(f"DB: {DB_PATH}")
print(f"NULL hrr_vector scan — {', '.join(CATEGORIES)}\n")

for cat in CATEGORIES:
    null_rows = conn.execute(
        "SELECT fact_id, content, trust_score, updated_at "
        "FROM facts WHERE category = ? AND hrr_vector IS NULL "
        "ORDER BY fact_id",
        (cat,),
    ).fetchall()
    n = len(null_rows)
    total_null += n
    if n == 0:
        print(f"{cat}: ✓ 0 null vectors")
    else:
        any_null = True
        print(f"{cat}: ✗ {n} null vectors (invisible to HRR bank)")
        for r in null_rows:
            preview = (r["content"] or "")[:100]
            print(f"  #{r['fact_id']} trust={r['trust_score']:.2f} updated={r['updated_at']}: {preview}")

# Cross-check against memory_banks
print()
bank_counts = {r["bank_name"].replace("cat:", ""): r["fact_count"]
               for r in conn.execute("SELECT bank_name, fact_count FROM memory_banks").fetchall()}

for cat in CATEGORIES:
    fact_count = conn.execute("SELECT COUNT(*) FROM facts WHERE category = ?", (cat,)).fetchone()[0]
    null_in_cat = conn.execute("SELECT COUNT(*) FROM facts WHERE category = ? AND hrr_vector IS NULL", (cat,)).fetchone()[0]
    bank_count = bank_counts.get(cat, "(no bank)")
    expected = fact_count - null_in_cat
    if str(bank_count) != str(expected):
        print(f"BANK MISMATCH: {cat} facts={fact_count} - null={null_in_cat} = {expected} in bank, but bank shows {bank_count}")
        any_null = True
    else:
        print(f"  {cat}: bank count {bank_count} matches facts ({fact_count}) - null ({null_in_cat}) = {expected}")

print()
if any_null:
    print(f"Janitor trigger: {total_null} NULL hrr_vectors found.")
    print("Fix: fact_store update each with verbatim current content. See SKILL.md Pass 0.")
    sys.exit(1)
else:
    print("All facts have non-null hrr_vectors. Bank is complete.")
    sys.exit(0)
