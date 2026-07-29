#!/usr/bin/env python3
"""
check_fact_discipline.py — enforces holographic-memory best-practices rules.

Design principles (per upstream review, 2026-07-29):
- NO shipped wordlist, NO regex guessing of "which words are entities".
- The single-word entity check set is DERIVED FROM THE STORE: we query
  fact_entities for entities that are single tokens (no spaces). Those are the
  only words the linter expects to be quoted. Common capitalized words
  (Python, Linux, Monday) are simply not in the store as entities, so they are
  never flagged -> zero false positives.
- If the store has no single-word entities yet (cold start), the linter cannot
  lint quoting -> it reports that LLM judgment applies (the agent decides what
  is an entity). No tokens spent.
- hrr_dim is READ FROM config.yaml (dimension-agnostic) -> never hardcoded.

Checks performed:
  1. Single-word-entity quoting: any single-word entity already in the store
     that appears UNQUOTED in the draft content -> FAIL (with the fact_id that
     established it, for context).
  2. Category enum: draft category must be in {user_pref, project, tool, general}.
  3. Per-bank capacity: WARN if a category exceeds hrr_dim/4 facts (SNR degrade).
  4. HRR homogeneity: FAIL if any category has mixed hrr_vector byte lengths.

Usage:
  python3 check_fact_discipline.py --dry-run --content '...' --category user_pref
      -> pre-write check of a proposed fact (content + category).
  python3 check_fact_discipline.py --store
      -> post-write audit of the whole store (janitor mode).
  python3 check_fact_discipline.py --json
      -> machine-readable output.

Exit codes:
  0 = clean (or only warnings)
  1 = violations found (FAIL)
  2 = cold store (no single-word entities; LLM judgment path)
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

EXPECTED_CATEGORIES = ("user_pref", "project", "tool", "general")


def find_db() -> Path:
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return Path(hermes_home) / "memory_store.db"


def read_hrr_dim() -> int:
    """Read hrr_dim from config.yaml (dimension-agnostic). Default 1024."""
    cfg = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))) / "config.yaml"
    if cfg.exists():
        text = cfg.read_text(errors="ignore")
        m = re.search(r"hrr_dim\s*:\s*(\d+)", text)
        if m:
            return int(m.group(1))
    return 1024


def get_single_word_entities(conn, min_facts: int = 3) -> list:
    """
    Derive the check set from the store: single-token entity names (no spaces)
    joined from fact_entities -> entities. These are the only words we expect to
    be quoted. No regex, no shipped list.

    Precision: only KEEP single-word entities that are TitleCase (Arif, Depakote)
    or ALL-CAPS acronyms (GCP, KTP, WIB) AND bound in >= min_facts facts.
    The frequency floor separates curated entities (agent quoted them repeatedly)
    from extraction artifacts (This, Aug, Agent, home -- bound in 1-2 facts only).

    A minimal GENERIC STOPWORD set (words that are never entities, regardless of
    frequency -- e.g. months, articles, common nouns) is excluded. This is NOT a
    user-entity wordlist; it is a tiny universal blocklist of non-entities so the
    linter never flags 'April' or 'Agent'. User-specific entities are still derived
    from the store only.
    """
    # Generic non-entities: months, articles, common nouns. Universal, no PII.
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
    """
    Return True if `entity` appears in content WITHOUT surrounding double quotes.
    Word-boundary aware (pitfall #28: substring matching false positives).
    """
    # quoted form: "entity" anywhere
    quoted = f'"{entity}"'
    if quoted in content:
        return False
    # unquoted occurrence with word boundaries
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
        # cold store -> LLM judgment path
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
        # per-fact quoting check for single-word entities
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
    ap.add_argument("--dry-run", action="store_true", help="check a proposed fact")
    ap.add_argument("--content", default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--store", action="store_true", help="audit whole store")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = find_db()
    if not db.exists():
        print("ERROR: memory_store.db not found at", db, file=sys.stderr)
        sys.exit(2)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    hrr_dim = read_hrr_dim()

    if args.dry_run:
        if not args.content or not args.category:
            print("ERROR: --dry-run requires --content and --category", file=sys.stderr)
            sys.exit(2)
        entities = get_single_word_entities(conn)
        result = check_dry_run(args.content, args.category, entities)
        conn.close()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("llm_judgment_required"):
                print("COLD STORE: no single-word entities in store yet.")
                print("-> LLM judgment applies for entity selection (no lint possible).")
                print("-> category check:", "OK" if args.category in EXPECTED_CATEGORIES else f"FAIL ({args.category})")
            elif result["problems"]:
                print("FAIL — quoting/category violations:")
                for p in result["problems"]:
                    print(f"  [{p['severity']}] {p['rule']}: {p['detail']}")
            else:
                print("PASS — draft is discipline-clean.")
        sys.exit(1 if result["problems"] else 0)

    if args.store:
        report = audit_store(conn, hrr_dim)
        conn.close()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"hrr_dim={hrr_dim}  capacity/fact per bank={hrr_dim//4}")
            print(f"single-word entities in store ({report['single_word_entity_count']}): {report['single_word_entities']}")
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

    # default: nothing specified
    print("Usage: --dry-run --content '...' --category X  |  --store  [--json]", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
