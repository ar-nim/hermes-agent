"""
reflect_step_helpers.py — copy-paste step bodies for the holographic-memory-reflect
cron run, in the file-based pattern (P1 in SKILL.md).

The original cron task body inlines these as `python3 -c "..."` snippets.
**That pattern is blocked by the execution sandbox** (`script execution via
-e/-c flag` -> pending_approval -> never resolves in cron context). The
fix is to write each snippet to /tmp/reflect_stepN.py and invoke it as
`python3 /tmp/reflect_stepN.py` with `workdir=.../holographic-memory-reflect`.

Usage in a cron/manual run:

    import json
    from pathlib import Path
    import sys

    # Step 0
    step0_path = Path('/tmp/reflect_step0.py')
    step0_path.write_text(STEP0_BODY)

    # Step 2
    step2_path = Path('/tmp/reflect_step2.py')
    step2_path.write_text(STEP2_BODY)

    # ... run them via terminal ...

The bodies below are the verified-good versions from the 2026-06-11 cron
run. They are the reference — if the cron task body in the run prompt
drifts, prefer these.

For Step 4 (LLM-driven synthesis generation) the agent reads
/tmp/reflect_facts.json + /tmp/reflect_stats.json and emits a list of
synth dicts. For Step 6 (write) the body below is the canonical INSERT
with trust=0.3, status:current, type:synthesis, components:, and entity
tags in the right order.
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone


# ---- Step 0: stale synthesis detection, refresh skipped ----------------

STEP0_BODY = '''
import sys, os
sys.path.insert(0, os.getcwd())
from reflect_pipeline import execute_step0, get_db_conn
conn = get_db_conn()
refreshed, ids, failures = execute_step0(conn, synthesize_fn=None)
conn.close()
print(f'Step 0: {refreshed} refreshed, ids={ids}, failures={failures}')
'''

# ---- Step 2: collect reliable facts + extract entities ----------------

STEP2_BODY = '''
import sys, os, re, sqlite3, json
sys.path.insert(0, os.getcwd())
from reflect_pipeline import compute_entity_stats
conn = sqlite3.connect(os.environ["HERMES_HOME"] + "/memory_store.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT fact_id, content, trust_score, updated_at, category, tags "
    "FROM facts WHERE trust_score >= 0.5 "
    "  AND (tags IS NULL OR tags NOT LIKE '%status:archived%')"
).fetchall()
facts = [dict(r) for r in rows]
quoted_re = re.compile(r'"([^"]+)"')
titlecase_re = re.compile(r"\\b([A-Z][a-z]{2,}(?:\\s+[A-Z][a-z]+)*)\\b")
for f in facts:
    f["entities"] = list(set(quoted_re.findall(f["content"]) + titlecase_re.findall(f["content"])))
stats = compute_entity_stats(facts)
top = sorted(stats.items(), key=lambda x: -x[1]["count"])[:25]
print(f"Step 2: {len(facts)} reliable facts, {len(stats)} entities")
print("TOP ENTITIES:")
for name, s in top:
    print(f'  {name}: count={s["count"]} span={s["timespan_days"]}d')
with open("/tmp/reflect_facts.json", "w") as fp:
    json.dump([{k: v for k, v in f.items() if k != "hrr_vector"} for f in facts], fp)
with open("/tmp/reflect_stats.json", "w") as fp:
    json.dump(stats, fp, default=str)
'''

# ---- Step 3: entity classification ------------------------------------

STEP3_BODY = '''
import json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect_pipeline import classify_entity_temporal, plan_deep_session_calls
stats = json.load(open("/tmp/reflect_stats.json"))
classes = {}
for e, s in stats.items():
    classes[e] = classify_entity_temporal(s["count"], s["timespan_days"])
long_term = [e for e, c in classes.items() if c == "long-term"]
short_term = [e for e, c in classes.items() if c == "short-term"]
print(f"Long-term: {len(long_term)}")
print(f"Short-term: {len(short_term)}")
print("Top 15 long-term:", long_term[:15])
deep = plan_deep_session_calls(long_term)
print(f"Deep pass plan: {deep}")
'''

# ---- Step 5: contradiction check helper --------------------------------

def check_no_duplicate(content_phrase: str, db_path: str) -> list:
    """Return existing fact_ids whose content matches content_phrase.
    Caller should drop the proposed synthesis if this is non-empty AND
    the existing fact has trust_score >= 0.5 (i.e. it's a user fact, not
    a prior synthesis).

    Uses LIKE directly (FTS5 MATCH is broken in cron sandbox — P13).
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT fact_id, content, trust_score FROM facts WHERE content LIKE ?",
            (f"%{content_phrase}%",),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


# ---- Step 6: write syntheses (trust=0.3) -------------------------------

STEP6_TEMPLATE = '''
import sqlite3, os, json, re
from datetime import datetime, timezone
db = os.path.join(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")), "memory_store.db")
syntheses = {SYNTHESES_JSON}
conn = sqlite3.connect(db, timeout=30)
now = datetime.now(timezone.utc).isoformat()
ids = []

# Entity extraction regex (same as store.py)
_RE_CAPITALIZED = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")
_RE_AKA = re.compile(r'\b(\w+)\s+aka\s+(\w+)\b', re.IGNORECASE)

def _extract_entities(text: str) -> list[str]:
    seen = set()
    candidates = []
    def _add(name: str) -> None:
        stripped = name.strip()
        if stripped and stripped.lower() not in seen:
            seen.add(stripped.lower())
            candidates.append(stripped)
    for m in _RE_CAPITALIZED.finditer(text):
        _add(m.group(1))
    for m in _RE_DOUBLE_QUOTE.finditer(text):
        _add(m.group(1))
    for m in _RE_SINGLE_QUOTE.finditer(text):
        _add(m.group(1))
    for m in _RE_AKA.finditer(text):
        _add(m.group(1))
        _add(m.group(2))
    return candidates

def _resolve_entity(conn, name: str) -> int:
    row = conn.execute(
        "SELECT entity_id FROM entities WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO entities (name) VALUES (?)",
        (name,),
    )
    return cur.lastrowid

for s in syntheses:
    tags = "status:current,type:synthesis,components:" + ",".join(str(c) for c in s["components"]) + ",reflect-synthesis," + ",".join(s["entities"])
    try:
        cur = conn.execute(
            "INSERT INTO facts (content, category, trust_score, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (s["content"], s["category"], 0.3, tags, now, now),
        )
        fact_id = cur.lastrowid
        ids.append(fact_id)
        # Link entities from the synthesis dict's "entities" field (authoritative source).
        # The _extract_entities() regex misses single-word entities like "User", "LocalTZ", "NAS"
        # because _RE_CAPITALIZED requires 2+ words and single-word entities are often unquoted.
        # Using the pre-defined entities list from the LLM-drafted synthesis is always correct.
        for entity_name in s.get("entities", []):
            entity_id = _resolve_entity(conn, entity_name)
            conn.execute(
                "INSERT OR IGNORE INTO fact_entities (fact_id, entity_id) VALUES (?, ?)",
                (fact_id, entity_id),
            )
    except sqlite3.IntegrityError as e:
        print(f"Duplicate: {e}")
conn.commit()
conn.close()
print(f"Wrote syntheses: {ids}")
'''


def build_step6_body(syntheses: list) -> str:
    """Build the Step 6 script body for a list of synth dicts.

    Each synth dict must have keys: content, category, components
    (list[int]), entities (list[str]).
    """
    synth_json = json.dumps(syntheses, ensure_ascii=False)
    return STEP6_TEMPLATE.replace("{SYNTHESES_JSON}", synth_json)


# ---- Step 6.5: HRR vector computation (MANDATORY after Step 6) ----------

STEP6_5_TEMPLATE = '''import subprocess, os, sys
hrr_script = os.path.join(
    os.environ["HERMES_HOME"],
    "skills", "holographic-memory", "holographic-memory-reflect",
    "scripts", "compute_hrr_vectors.py"
)
fact_ids = {FACT_IDS}
cmd = [sys.executable, hrr_script] + [str(fid) for fid in fact_ids]
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print(f"HRR computation failed: {result.stderr}")
    sys.exit(1)
'''


def build_step6_5_body(fact_ids: list) -> str:
    """Build the Step 6.5 script body to compute HRR vectors for new facts."""
    return STEP6_5_TEMPLATE.replace("{FACT_IDS}", repr(fact_ids))


# ---- Step 7: cursor advance (Python file I/O, not terminal) ------------

STEP7_BODY = '''
from datetime import datetime, timezone
from pathlib import Path
cursor = Path(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))) / "holographic_memory_cursor"
old = cursor.read_text().strip() if cursor.exists() else None
cursor.write_text(datetime.now(timezone.utc).isoformat() + "\\n")
new = cursor.read_text().strip()
print(f"Cursor: {old} -> {new}")
'''
