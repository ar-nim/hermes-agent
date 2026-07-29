import os
#!/usr/bin/env python3
"""Entity binding rate diagnostic for key entities.

Usage:
  python3 check_entity_binding_rates.py              # check default key entities
  python3 check_entity_binding_rates.py User ConditionA CityX  # check specific entities

Environment:
  - Uses $HERMES_HOME/memory_store.db (SQLite format)
  - Works in cron context via terminal("python3 ...")

Interpretation:
  - Rate >= 0.85: Healthy
  - Rate 0.70-0.85: Warning — investigate unbound facts
  - Rate < 0.70: Critical — significant binding gap

The rate = bound_facts / fts_mentions. A rate of 1.0 means every fact mentioning
the entity is also entity-bound (HRR-indexed). Low rates mean probe() will miss
those facts — they're only retrievable via FTS5 keyword search.
"""
import sqlite3
import sys

DB_PATH = os.path.join(os.path.expanduser(os.environ.get('HERMES_HOME', '~/.hermes')), '.hermes', 'memory_store.db')

# Default key entities — high-value synthesis nodes that span multiple domains
DEFAULT_ENTITIES = [
    'User', 'ConditionA', 'MedicationB', 'CityX', 'CountryY',
    'Partner', 'InsurerD', 'InsurerC', 'EmployerE', 'Kubernetes',
    'CityRail', 'NationalWeatherAPI', 'NAS', 'Syncthing', 'CommunityOrg',
]

def check_binding_rates(entities):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA query_only=ON')
    conn.row_factory = sqlite3.Row

    results = []
    for entity in entities:
        # FTS mentions: how many facts contain this entity in content
        cur = conn.execute(
            'SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ?',
            (f'"{entity}"',)
        )
        fts_count = cur.fetchone()[0]

        # Bound facts: how many facts are linked to this entity in fact_entities
        cur = conn.execute(
            'SELECT COUNT(*) FROM fact_entities fe '
            'JOIN entities e ON e.entity_id = fe.entity_id '
            'WHERE e.name = ?',
            (entity,)
        )
        bound_count = cur.fetchone()[0]

        rate = round(bound_count / fts_count, 3) if fts_count > 0 else None

        if rate is None:
            status = 'N/A'
        elif rate >= 0.85:
            status = 'OK'
        elif rate >= 0.70:
            status = 'WARNING'
        else:
            status = 'CRITICAL'

        results.append({
            'entity': entity,
            'rate': rate,
            'status': status,
            'bound': bound_count,
            'fts': fts_count,
        })

    conn.close()
    return results

def main():
    if len(sys.argv) > 1:
        entities = sys.argv[1:]
    else:
        entities = DEFAULT_ENTITIES

    results = check_binding_rates(entities)

    # Sort by rate ascending (worst first)
    results.sort(key=lambda x: x['rate'] if x['rate'] is not None else -1)

    triggered = [r for r in results if r['status'] in ('CRITICAL', 'WARNING')]

    for r in results:
        rate_str = f"{r['rate']:.3f}" if r['rate'] is not None else 'N/A'
        print(f"{r['entity']}: {rate_str} ({r['status']}) — {r['bound']}/{r['fts']} bound")

    if triggered:
        print(f"\n⚠️ {len(triggered)} entity(ies) below healthy threshold:")
        for t in triggered:
            rate_str = f"{t['rate']:.3f}" if t['rate'] is not None else 'N/A'
            print(f"  - {t['entity']}: {rate_str} ({t['status']}) — {t['bound']}/{t['fts']}")
    else:
        print("\nAll checked entities healthy.")

    return 1 if triggered else 0

if __name__ == '__main__':
    sys.exit(main())
