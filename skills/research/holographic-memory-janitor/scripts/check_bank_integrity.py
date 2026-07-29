#!/usr/bin/env python3
"""
check_bank_integrity.py — per-category HRR vector byte-length audit.

Detects the "inhomogeneous shape" bank corruption: when a fact's hrr_vector
is stored at a different dimensionality than the rest of the category bank,
every subsequent _rebuild_bank() fails with numpy's inhomogeneous shape error.

Usage:
    python3 scripts/check_bank_integrity.py
    python3 scripts/check_bank_integrity.py --json

Exit codes:
    0 = all banks homogeneous
    1 = at least one bank has outliers (corruption present)
    2 = no facts at all (cold store)

Output format (default):
    user_pref: 227 vectors, byte_lens={32768: 224, 8192: 3} ✗ CORRUPT
      #831 byte_len=8192 (expected 32768)
      #832 byte_len=8192 (expected 32768)
      #833 byte_len=8192 (expected 32768)

The expected byte_len is hrr_dim * 8 (float64). For the configured default
hrr_dim=4096, expected is 32768 bytes per vector.

See: references/bank-corruption-diagnosis.md
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

EXPECTED_CATEGORIES = ("user_pref", "general", "tool", "project")
EXPECTED_DIM = 4096  # matches ~/.hermes/config.yaml holographic_memory.hrr_dim
EXPECTED_BYTES = EXPECTED_DIM * 8  # float64


def find_db() -> Path:
    hermes_home = os.environ.get(
        "HERMES_HOME", os.path.expanduser("~/.hermes")
    )
    return Path(hermes_home) / "memory_store.db"


def audit(db_path: Path) -> dict:
    """Return per-category integrity report."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    report: dict = {"db_path": str(db_path), "categories": {}, "expected_bytes": EXPECTED_BYTES}

    for cat in EXPECTED_CATEGORIES:
        rows = conn.execute(
            "SELECT fact_id, length(hrr_vector) AS byte_len "
            "FROM facts WHERE category = ? AND hrr_vector IS NOT NULL",
            (cat,),
        ).fetchall()
        null_count = conn.execute(
            "SELECT COUNT(*) AS c FROM facts "
            "WHERE category = ? AND hrr_vector IS NULL",
            (cat,),
        ).fetchone()["c"]

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
            "total_with_vector": len(rows),
            "null_vector": null_count,
            "byte_len_distribution": dict(lens),
            "outliers": outliers,
            "homogeneous": len(outliers) == 0,
        }

    # Check memory_banks for orphan rows (categories that shouldn't exist)
    orphan_banks = []
    bank_rows = conn.execute("SELECT bank_name FROM memory_banks").fetchall()
    valid_banks = {f"cat:{c}" for c in EXPECTED_CATEGORIES}
    for row in bank_rows:
        if row["bank_name"] not in valid_banks:
            orphan_banks.append(row["bank_name"])
    report["orphan_banks"] = orphan_banks

    conn.close()
    return report


def format_human(report: dict) -> str:
    lines = []
    any_corrupt = False
    for cat, info in report["categories"].items():
        status = "✓ OK" if info["homogeneous"] else "✗ CORRUPT"
        if not info["homogeneous"]:
            any_corrupt = True
        lens = info["byte_len_distribution"]
        lens_str = ", ".join(f"{b}B: {n}" for b, n in sorted(lens.items(), key=lambda x: -x[1]))
        lines.append(
            f"{cat}: {info['total_with_vector']} vectors, "
            f"byte_lens={{{lens_str}}} {status}"
        )
        if info["null_vector"]:
            lines.append(f"  {info['null_vector']} fact(s) with NULL hrr_vector (invisible to HRR algebra)")
        for o in info["outliers"]:
            lines.append(f"  #{o['fact_id']} byte_len={o['byte_len']} (expected {report['expected_bytes']})")

    if report["orphan_banks"]:
        lines.append("")
        lines.append(f"Orphan banks in memory_banks: {report['orphan_banks']}")

    lines.append("")
    lines.append("Janitor trigger check: "
                 + ("Bank corruption detected — run Pass 0: Bank Integrity Repair."
                    if any_corrupt
                    else "All banks homogeneous."))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of human format")
    parser.add_argument("--db", type=Path, default=None, help="override DB path (default: $HERMES_HOME/memory_store.db)")
    args = parser.parse_args()

    db_path = args.db or find_db()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2

    report = audit(db_path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human(report))

    any_corrupt = any(not info["homogeneous"] for info in report["categories"].values())
    return 1 if any_corrupt else 0


if __name__ == "__main__":
    sys.exit(main())
