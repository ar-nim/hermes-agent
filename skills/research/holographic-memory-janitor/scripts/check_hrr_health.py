#!/usr/bin/env python3
"""
check_hrr_health.py — HRR vector integrity audit.

Detects two failure modes:
  1. Inhomogeneous byte-length vectors (wrong dimensionality → bank corruption)
  2. NULL hrr_vectors (silently excluded from bank rebuilds)

Uses MemoryStore shared connection. Dimension-agnostic (reads store.hrr_dim).

Usage:
    python3 check_hrr_health.py
    python3 check_hrr_health.py --db /path/to/test.db
    python3 check_hrr_health.py --json

Exit codes: 0=all healthy, 1=problems found
"""
import argparse
import os
import sys
from pathlib import Path
from collections import Counter

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_AGENT_DIR = HERMES_HOME / "hermes-agent"
_HOLO_DIR = _AGENT_DIR / "plugins" / "memory" / "holographic"
for _p in [str(_HOLO_DIR), str(_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

CATEGORIES = ("user_pref", "general", "tool", "project")


def get_store(db_path=None):
    """Get a MemoryStore using the plugin's shared connection."""
    from store import MemoryStore
    if db_path is None:
        db_path = str(HERMES_HOME / "memory_store.db")
    return MemoryStore(db_path=db_path)


def audit_hrr_health(db_path=None) -> dict:
    """
    Audit HRR vector integrity across all categories.

    Returns dict with:
        corrupt: bool — True if any inhomogeneous vectors found
        null_count: int — total facts with NULL hrr_vector
        expected_bytes: int — hrr_dim * 8 (float64)
        categories: {cat: {total, null, byte_len_dist, outliers, homogeneous}}
    """
    store = get_store(db_path)
    hrr_dim = store.hrr_dim
    expected_bytes = hrr_dim * 8

    report = {
        "corrupt": False,
        "null_count": 0,
        "expected_bytes": expected_bytes,
        "hrr_dim": hrr_dim,
        "categories": {},
    }

    with store._lock:
        for cat in CATEGORIES:
            rows = store._conn.execute(
                "SELECT fact_id, length(hrr_vector) AS byte_len "
                "FROM facts WHERE category = ? AND hrr_vector IS NOT NULL",
                (cat,),
            ).fetchall()

            null_count = store._conn.execute(
                "SELECT COUNT(*) FROM facts WHERE category = ? AND hrr_vector IS NULL",
                (cat,),
            ).fetchone()[0]

            lens = Counter(r["byte_len"] for r in rows)
            outliers = []
            if lens:
                majority = lens.most_common(1)[0][0]
                outliers = [
                    {"fact_id": r["fact_id"], "byte_len": r["byte_len"]}
                    for r in rows
                    if r["byte_len"] != majority
                ]

            report["categories"][cat] = {
                "total": len(rows),
                "null": null_count,
                "byte_len_distribution": dict(lens),
                "outliers": outliers,
                "homogeneous": len(outliers) == 0,
            }
            report["null_count"] += null_count
            if outliers:
                report["corrupt"] = True

    store.close()
    return report


def format_human(report: dict) -> str:
    lines = []
    lines.append(f"hrr_dim={report['hrr_dim']}  expected_bytes={report['expected_bytes']}")

    for cat, info in report["categories"].items():
        status = "✓ OK" if info["homogeneous"] else "✗ CORRUPT"
        lens = info["byte_len_distribution"]
        lens_str = ", ".join(f"{b}B: {n}" for b, n in sorted(lens.items(), key=lambda x: -x[1]))
        lines.append(f"  {cat}: {info['total']} vectors, {{{lens_str}}} {status}")
        if info["null"]:
            lines.append(f"    {info['null']} fact(s) with NULL hrr_vector (invisible to HRR)")
        for o in info["outliers"]:
            lines.append(f"    #{o['fact_id']} byte_len={o['byte_len']} (expected {report['expected_bytes']})")

    if report["null_count"]:
        lines.append(f"\n{report['null_count']} NULL vectors found.")
    if report["corrupt"]:
        lines.append("\n✗ Bank corruption detected — run janitor Pass 1.")
    elif not report["null_count"]:
        lines.append("\n✓ All vectors homogeneous and non-null.")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="override DB path")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    report = audit_hrr_health(args.db)
    if args.json:
        import json
        print(json.dumps(report, indent=2))
    else:
        print(format_human(report))

    return 1 if (report["corrupt"] or report["null_count"]) else 0


if __name__ == "__main__":
    sys.exit(main())
