#!/usr/bin/env python3
"""
run_steps012.py — Combined CLI entry point for Steps 0, 1, 2.

1. Step 0: stale synthesis detection + no-op refresh (LLM generates content)
2. Step 1: collect reliable facts (trust >= 0.5, non-archived)
3. Step 2: entity statistics computation

All DB access via MemoryStore's shared connection.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect_pipeline import execute_step0, get_store, collect_reliable_facts
from reflect_logic import compute_entity_stats

store = get_store()

# ── Step 0: stale synthesis refresh ─────────────────────────────────────────
def noop(facts):
    return None

refreshed, ids, failures = execute_step0(store, synthesize_fn=noop)
print(f"Step 0: refreshed={refreshed}, ids={ids}, failures={failures}")

# ── Step 1: full corpus collection ─────────────────────────────────────────
facts = collect_reliable_facts(store, min_trust=0.5)
print(f"Step 1: {len(facts)} facts collected (trust>=0.5, non-archived)")

# ── Step 2: entity stats ────────────────────────────────────────────────────
entity_stats = compute_entity_stats(facts)
print(f"Step 2: {len(facts)} facts, {len(entity_stats)} entities")
for name, stats in sorted(entity_stats.items(), key=lambda x: -x[1]['count'])[:20]:
    print(f"  {name}: count={stats['count']}, timespan_days={stats['timespan_days']}")

store.close()
