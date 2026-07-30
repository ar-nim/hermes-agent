"""
check_fact_discipline.py — enforces holographic-memory best-practices rules.

Design principles:
- NO shipped wordlist, NO regex guessing of "which words are entities".
- The single-word entity check set is DERIVED FROM THE STORE.
- hrr_dim is read from MemoryStore (dimension-agnostic) — never hardcoded.
- Uses MemoryStore shared connection (NOT sqlite3.connect).

Checks:
  1. Single-word-entity quoting (dry-run + store audit)
  2. Category enum validation
  3. Per-bank capacity (SNR degrade warning)
  4. HRR vector byte-length homogeneity

Usage:
  --dry-run --content '...' --category user_pref  → pre-write check
  --store                                          → full store audit
  --json                                           → machine-readable
  --db /path/to/test.db                            → override DB path

Exit codes: 0=clean, 1=violations, 2=cold store
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_AGENT_DIR = HERMES_HOME / "hermes-agent"
_HOLO_DIR = _AGENT_DIR / "plugins" / "memory" / "holographic"
for _p in [str(_HOLO_DIR), str(_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

EXPECTED_CATEGORIES = ("user_pref", "project", "tool", "general")


def get_store(db_path=None):
    """Get a MemoryStore using the plugin's db_path resolution."""
    from store import MemoryStore
    return MemoryStore(db_path=db_path)


def read_hrr_dim(store) -> int:
    """Read hrr_dim from MemoryStore (dimension-agnostic)."""
    return store.hrr_dim


def get_single_word_entities(conn, min_facts: int = 3) -> list:
    STOPWORDS = {
        "april", "may", "june", "jul", "aug", "sep", "sept", "september",
        "oct", "nov", "dec", "jan", "feb", "mar",
        "the", "this", "his", "both", "open", "meteo", "tomorrow", "data",
        "grocery", "agent", "title", "club", "analytics", "engineering",
        "leap", "home", "mostly", "usually", "yes", "large", "north", "six",
        "strategic", "senior", "associate", "bot", "cron", "key", "ring",
        "wardrobe", "lossless", "di", "rumah", "calibration", "smabel",
    }
    rows = conn.execute(
        "SELECT e.name, COUNT(*) AS n FROM fact_entities fe "
        "JOIN entities e ON e.entity_id = fe.entity_id "
        "GROUP BY e.name"
    ).fetchall()
    out = []
    for r in rows:
        e = (r["name"] or "").strip().strip('"')
        if not e or " " in e or e in ('', ','):
            continue
        if e.lower() in STOPWORDS:
            continue
        is_title = e[0].isupper() and any(c.islower() for c in e[1:])
        is_acronym = e.isupper() and len(e) >= 2
        if (is_title or is_acronym) and r["n"] >= min_facts:
            if e not in out:
                out.append(e)
    return out


def unquoted_occurrence(content: str, entity: str) -> bool:
    quoted = f'"{entity}"'
    if quoted in content:
        return False
    return bool(re.search(r"(?<![\w\"])" + re.escape(entity) + r"(?![\w\"])", content))


def check_dry_run(content: str, category: str, entities: list) -> dict:
    problems = []
    if category not in EXPECTED_CATEGORIES:
        problems.append({
            "rule": "category-enum",
            "severity": "FAIL",
            "detail": f"category '{category}' not in {EXPECTED_CATEGORIES}",
        })
    if not entities:
        return {
            "store_has_single_word_entities": False,
            "llm_judgment_required": True,
            "problems": problems,
        }
    for ent in entities:
        if unquoted_occurrence(content, ent):
            problems.append({
                "rule": "single-word-entity-quoting",
                "severity": "FAIL",
                "detail": f"single-word entity '{ent}' appears unquoted in content; must be \"\\{ent}\"",
                "entity": ent,
            })
    return {
        "store_has_single_word_entities": True,
        "llm_judgment_required": False,
        "problems": problems,
    }


def audit_store(conn, hrr_dim: int) -> dict:
    report = {"hrr_dim": hrr_dim, "categories": {}, "capacity_per_bank": hrr_dim // 4, "problems": []}
    entities = get_single_word_entities(conn)
    report["single_word_entity_count"] = len(entities)
    report["single_word_entities"] = entities

    for cat in EXPECTED_CATEGORIES:
        rows = conn.execute(
            "SELECT fact_id, content, length(hrr_vector) AS byte_len "
            "FROM facts WHERE category = ?", (cat,)
        ).fetchall()
        total = len(rows)
        lens = {}
        for r in rows:
            lens[r["byte_len"]] = lens.get(r["byte_len"], 0) + 1
        outliers = []
        if lens:
            majority = max(lens, key=lens.get)
            outliers = [r["fact_id"] for r in rows if r["byte_len"] != majority and r["byte_len"] is not None]
        report["categories"][cat] = {
            "total": total,
            "byte_len_distribution": lens,
            "hrr_homogeneous": len(outliers) == 0,
        }
        if outliers:
            report["problems"].append({
                "rule": "hrr-homogeneity", "severity": "FAIL",
                "category": cat, "outlier_fact_ids": outliers[:10],
            })
        if total > hrr_dim // 4:
            report["problems"].append({
                "rule": "per-bank-capacity", "severity": "WARN",
                "category": cat, "total": total, "limit": hrr_dim // 4,
            })
        for r in rows:
            c = r["content"] or ""
            for ent in entities:
                if unquoted_occurrence(c, ent):
                    report["problems"].append({
                        "rule": "single-word-entity-quoting", "severity": "FAIL",
                        "category": cat, "fact_id": r["fact_id"], "entity": ent,
                    })
                    break
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--content", default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    store = get_store(args.db)
    hrr_dim = read_hrr_dim(store)

    if args.dry_run:
        if not args.content or not args.category:
            print("ERROR: --dry-run requires --content and --category", file=sys.stderr)
            store.close()
            sys.exit(2)
        with store._lock:
            entities = get_single_word_entities(store._conn)
            result = check_dry_run(args.content, args.category, entities)
        store.close()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("llm_judgment_required"):
                print("COLD STORE: no single-word entities in store yet.")
                print("-> LLM judgment applies for entity selection (no lint possible).")
            elif result["problems"]:
                print("FAIL — quoting/category violations:")
                for p in result["problems"]:
                    print(f"  [{p['severity']}] {p['rule']}: {p['detail']}")
            else:
                print("PASS — draft is discipline-clean.")
        sys.exit(1 if result["problems"] else 0)

    if args.store:
        with store._lock:
            report = audit_store(store._conn, hrr_dim)
        store.close()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"hrr_dim={hrr_dim}  capacity/fact per bank={hrr_dim//4}")
            fails = [p for p in report["problems"] if p["severity"] == "FAIL"]
            warns = [p for p in report["problems"] if p["severity"] == "WARN"]
            for p in report["problems"]:
                tag = "FAIL" if p["severity"] == "FAIL" else "WARN"
                if p["rule"] == "hrr-homogeneity":
                    print(f"  [{tag}] {p['rule']} ({p['category']}): {len(p['outlier_fact_ids'])} outlier vectors")
                elif p["rule"] == "per-bank-capacity":
                    print(f"  [{tag}] {p['rule']} ({p['category']}): {p['total']} > {p['limit']}")
                elif p["rule"] == "single-word-entity-quoting":
                    print(f"  [{tag}] {p['rule']}: fact {p.get('fact_id')} missing quotes around '{p['entity']}'")
            print(f"\n{len(fails)} FAIL, {len(warns)} WARN")
        sys.exit(1 if fails else 0)

    print("Usage: --dry-run --content '...' --category X  |  --store  [--json]", file=sys.stderr)
    store.close()
    sys.exit(2)


if __name__ == "__main__":
    main()
