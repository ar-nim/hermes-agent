#!/usr/bin/env python3
"""
run_step2.py — CLI entry point for Step 2: entity statistics computation.

Uses collect_reliable_facts + compute_entity_stats to produce per-entity
mention counts and timespans. Outputs top-20 entities to stdout.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect_pipeline import get_store, collect_reliable_facts
from reflect_logic import compute_entity_stats

store = get_store()
facts = collect_reliable_facts(store, min_trust=0.5)
store.close()

entity_stats = compute_entity_stats(facts)
print(f"Step 2: {len(facts)} facts, {len(entity_stats)} entities")
for name, stats in sorted(entity_stats.items(), key=lambda x: -x[1]['count'])[:20]:
    print(f"  {name}: count={stats['count']}, timespan_days={stats['timespan_days']}")
