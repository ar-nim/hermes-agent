#!/usr/bin/env python3
"""
check_entity_bindings.py — entity binding rate audit.

Derives entity list from the store (fact_entities JOIN entities), not a
hardcoded wordlist. For each entity, computes:
  - fts_mentions: how many facts contain the entity in content
  - bound: how many facts are linked via fact_entities
  - rate = bound / fts_mentions

Uses MemoryStore shared connection. Dimension-agnostic.

Usage:
    python3 check_entity_bindings.py
    python3 check_entity_bindings.py --db /path/to/test.db
    python3 check_entity_bindings.py --json

Exit codes: 0=all healthy, 1=entities below threshold
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_AGENT_DIR = HERMES_HOME / "hermes-agent"
_HOLO_DIR = _AGENT_DIR / "plugins" / "memory" / "holographic"
for _p in [str(_HOLO_DIR), str(_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Generic non-entities: months, articles, common nouns. Universal, no PII.
STOPWORDS = {
    "april", "may", "june", "jul", "aug", "sep", "sept", "september",
    "oct", "nov", "dec", "jan", "feb", "mar",
    "the", "this", "his", "both", "open", "meteo", "tomorrow", "data",
    "grocery", "agent", "title", "club", "analytics", "engineering",
    "leap", "home", "mostly", "usually", "yes", "large", "north", "six",
    "strategic", "senior", "associate", "bot", "cron", "key", "ring",
}

MIN_FACTS = 3  # frequency floor — entity must be bound in >= 3 facts


def get_store(db_path=None):
    """Get a MemoryStore using the plugin's shared connection."""
    from store import MemoryStore
    if db_path is None:
        db_path = str(HERMES_HOME / "memory_store.db")
    return MemoryStore(db_path=db_path)


def derive_entities(store) -> list:
    """
    Derive entity list from the store. Single-word TitleCase or ALL-CAPS
    acronyms bound in >= MIN_FACTS facts. Not a shipped wordlist.
    """
    with store._lock:
        rows = store._conn.execute(
            "SELECT e.name, COUNT(*) AS n "
            "FROM fact_entities fe JOIN entities e ON e.entity_id = fe.entity_id "
            "GROUP BY e.name"
        ).fetchall()

    out = []
    for r in rows:
        name = (r["name"] or "").strip().strip('"')
        if not name or " " in name:
            continue
        if name.lower() in STOPWORDS:
            continue
        is_title = name[0].isupper() and any(c.islower() for c in name[1:])
        is_acronym = name.isupper() and len(name) >= 2
        if (is_title or is_acronym) and r["n"] >= MIN_FACTS:
            if name not in out:
                out.append(name)
    return out


def audit_entity_bindings(db_path=None) -> dict:
    """
    Audit entity binding rates for all store-derived entities.

    Returns dict with:
        entities: [{entity, fts, bound, rate, status}]
        any_below_threshold: bool
    """
    store = get_store(db_path)
    entities = derive_entities(store)
    results = []

    with store._lock:
        for name in entities:
            # FTS mentions: how many facts contain this entity in content
            try:
                fts_row = store._conn.execute(
                    "SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ?",
                    (f'"{name}"',),
                ).fetchone()
                fts_count = fts_row[0] if fts_row else 0
            except Exception:
                fts_count = 0

            # Bound facts: how many are linked via fact_entities
            bound_row = store._conn.execute(
                "SELECT COUNT(*) FROM fact_entities fe "
                "JOIN entities e ON e.entity_id = fe.entity_id "
                "WHERE e.name = ?",
                (name,),
            ).fetchone()
            bound_count = bound_row[0] if bound_row else 0

            if fts_count > 0:
                rate = round(bound_count / fts_count, 3)
            else:
                rate = None

            if rate is None:
                status = "N/A"
            elif rate >= 0.85:
                status = "OK"
            elif rate >= 0.70:
                status = "WARNING"
            else:
                status = "CRITICAL"

            results.append({
                "entity": name,
                "fts": fts_count,
                "bound": bound_count,
                "rate": rate,
                "status": status,
            })

    store.close()

    results.sort(key=lambda x: x["rate"] if x["rate"] is not None else -1)
    any_below = any(r["status"] in ("WARNING", "CRITICAL") for r in results)

    return {"entities": results, "any_below_threshold": any_below}


def format_human(report: dict) -> str:
    lines = []
    entities = report["entities"]

    if not entities:
        lines.append("No store-derived entities found (cold store or < 3 facts each).")
        return "\n".join(lines)

    for e in entities:
        rate_str = f"{e['rate']:.3f}" if e["rate"] is not None else "N/A"
        lines.append(f"  {e['entity']}: {rate_str} ({e['status']}) — {e['bound']}/{e['fts']} bound")

    triggered = [e for e in entities if e["status"] in ("WARNING", "CRITICAL")]
    if triggered:
        lines.append(f"\n⚠️ {len(triggered)} entity(ies) below healthy threshold:")
        for t in triggered:
            rate_str = f"{t['rate']:.3f}" if t["rate"] is not None else "N/A"
            lines.append(f"  - {t['entity']}: {rate_str} ({t['status']}) — {t['bound']}/{t['fts']}")
    else:
        lines.append("\n✓ All checked entities healthy.")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="override DB path")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    report = audit_entity_bindings(args.db)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human(report))

    return 1 if report["any_below_threshold"] else 0


if __name__ == "__main__":
    sys.exit(main())
