#!/usr/bin/env python3
"""Check seed anchors and report trigger status.

Usage: python3 check_anchors.py

Environment:
  - Uses $HERMES_HOME/memory_store.db (SQLite format)
  - file command confirms: "SQLite 3.x database" (NOT DuckDB)
  - sqlite3 module works directly on this path

Important notes (May 23 2026):
  - fact_store tool NOT available in cron execution context (tool not exposed)
  - execute_code also lacks fact_store (hermes_tools doesn't export it)
  - terminal with python3 subprocess is the correct approach
  - DuckDB python module fails: "Table with name facts does not exist"
  - The ~4KB DuckDB file at $HERMES_HOME/memory_store.db
    is the WRONG file - use $HERMES_HOME/memory_store.db (SQLite)
"""

import sqlite3
import os
import subprocess

DB_PATH = os.path.join(os.path.expanduser(os.environ.get('HERMES_HOME', '~/.hermes')), '.hermes', 'memory_store.db')

def check_anchors():
    print(f"DB path: {DB_PATH}")
    result = subprocess.run(['file', DB_PATH], capture_output=True, text=True)
    print(f"File type: {result.stdout.strip()}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA query_only=ON')
    conn.row_factory = sqlite3.Row

    # Get total facts
    cur = conn.execute('SELECT COUNT(*) FROM facts')
    fc = cur.fetchone()[0]
    print(f'Total facts: {fc}')

    # Get FTS count
    cur = conn.execute('SELECT COUNT(*) FROM facts_fts')
    fts = cur.fetchone()[0]
    print(f'FTS entries: {fts}')

    # Calculate drift
    drift = abs(fts - fc) / fc if fc > 0 else 0
    print(f'FTS drift: {drift:.4f}')

    # Get seed anchors
    cur = conn.execute('''
        SELECT e.name, f.content, f.fact_id
        FROM facts f
        JOIN fact_entities fe ON fe.fact_id = f.fact_id
        JOIN entities e ON e.entity_id = fe.entity_id
        WHERE f.tags LIKE '%seed_anchor%'
    ''')
    anchors = []
    for row in cur.fetchall():
        content = row['content']
        name_in_content = content.split(',')[0].replace('seed_anchor:', '').strip()
        parts = {}
        for p in content.split(','):
            if '=' in p:
                k, v = p.split('=', 1)
                parts[k.strip()] = v.strip()
        # Use row['name'] (entity table name) as the authoritative anchor name
        # name_in_content may include quotes from content formatting (e.g., '"ConditionA"')
        # but the entity table stores bare names ('ConditionA', not '"ConditionA"')
        anchors.append({
            'name': row['name'],  # authoritative — from entities table
            'threshold': float(parts.get('threshold', 0.85)),
            'critical': parts.get('critical', 'false') == 'true',
            'fact_id': row['fact_id']
        })

    print(f'\nFound {len(anchors)} seed anchors')

    triggered = []
    for anchor in anchors:
        # FTS count: facts where this name appears in CONTENT column (not tags)
        # Use content:ConditionA syntax to search content column only — avoids tag inflation
        cur = conn.execute(
            'SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ? AND rowid != ?',
            (f'content:{anchor["name"]}', anchor['fact_id'])
        )
        total = cur.fetchone()[0]

        # Bound count
        cur = conn.execute(
            'SELECT COUNT(*) FROM fact_entities fe JOIN entities e ON e.entity_id = fe.entity_id WHERE e.name = ?',
            (anchor['name'],)
        )
        bound = cur.fetchone()[0]

        rate = round(bound / total, 3) if total > 0 else 0.0
        status = "OK" if rate >= anchor['threshold'] else "TRIGGER"
        gap = round(anchor['threshold'] - rate, 3)
        print(f"{anchor['name']}: {rate:.3f} ({status}) — {bound}/{total} bound, threshold={anchor['threshold']}, gap={gap}, critical={anchor['critical']}")
        
        if status == "TRIGGER":
            triggered.append({
                'name': anchor['name'],
                'rate': rate,
                'threshold': anchor['threshold'],
                'gap': gap,
                'bound': bound,
                'total': total,
                'critical': anchor['critical']
            })

    conn.close()
    
    return triggered

if __name__ == '__main__':
    triggered = check_anchors()
    if triggered:
        print(f"\n⚠️ JANITOR TRIGGER — {len(triggered)} anchor(s) below threshold")
        for t in triggered:
            print(f"- {t['name']}: {t['rate']:.3f} (threshold={t['threshold']}, gap={t['gap']}) — {t['bound']}/{t['total']} bound, critical={t['critical']}")
    else:
        print("\nJanitor trigger check: All anchors healthy.")