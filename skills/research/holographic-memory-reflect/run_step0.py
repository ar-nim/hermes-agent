#!/usr/bin/env python3
"""
run_step0.py — CLI entry point for Step 0: stale synthesis refresh.

Called by the reflect cron (LLM-driven, skip_memory=True). Uses MemoryStore
to read/write the DB directly (fact_store is unavailable in cron context).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect_pipeline import execute_step0, get_store

store = get_store()

def noop_synthesize(facts):
    """No-op: the cron's LLM generates actual synthesis content."""
    return None

refreshed, ids, failures = execute_step0(store, synthesize_fn=noop_synthesize)
store.close()
print(f"Step 0: refreshed={refreshed}, ids={ids}, failures={failures}")
