"""
reflect_pipeline.py — DB-coupled reflect pipeline operations.

Uses MemoryStore's shared connection (NOT sqlite3.connect) to avoid WAL
contention. fact_store is unavailable in cron context (skip_memory=True
hardcoded in scheduler.py:3466), so all DB access goes through MemoryStore.

Imports pure functions from reflect_logic for computation.
"""
import os, re, sys
from datetime import datetime, timezone

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
_AGENT_DIR = os.path.join(HERMES_HOME, "hermes-agent")
_HOLO_DIR = os.path.join(_AGENT_DIR, "plugins", "memory", "holographic")
for _p in [_HOLO_DIR, _AGENT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from reflect_logic import detect_staleness


# =============================================================================
# MemoryStore Factory
# =============================================================================

def get_store(db_path=None):
    """
    Get a MemoryStore instance using the plugin's shared connection.

    Use this instead of sqlite3.connect() to join the plugin's connection pool
    and avoid WAL lock contention (the shared pool eliminates cross-connection
    contention; see store.py:98-112).

    Args:
        db_path: override DB path. Defaults to HERMES_HOME/memory_store.db
    """
    from store import MemoryStore
    if db_path is None:
        db_path = os.path.join(HERMES_HOME, "memory_store.db")
    return MemoryStore(db_path=db_path)


# =============================================================================
# Step 0: Stale Synthesis Refresh
# =============================================================================

def execute_step0(store, synthesize_fn):
    """
    Execute Step 0: detect stale syntheses and refresh them in-place.

    Args:
        store: MemoryStore instance (shared connection + lock)
        synthesize_fn: callable(component_facts: list[dict]) -> str

    Returns:
        (refreshed_count: int, refreshed_ids: list[int], failures: list[int])
    """
    with store._lock:
        rows = store._conn.execute("""
            SELECT fact_id, content, created_at, updated_at, category, tags
            FROM facts
            WHERE tags LIKE '%status:current%'
              AND tags LIKE '%type:synthesis%'
        """).fetchall()

    refreshed_count = 0
    refreshed_ids = []
    failures = []

    for row in rows:
        fact_id = row["fact_id"]
        tags = row["tags"] or ""

        # Parse component IDs from tags
        component_ids = []
        comp_match = re.search(r'components:([\d,]+)', tags)
        if comp_match:
            component_ids = [int(x) for x in comp_match.group(1).split(",") if x.strip().isdigit()]

        if not component_ids:
            continue

        synthesis = {
            "fact_id": fact_id,
            "content": row["content"],
            "created_at": row["created_at"],
            "category": row["category"],
            "tags": tags,
            "components": component_ids,
        }

        # Fetch component timestamps
        components = {}
        with store._lock:
            for comp_id in component_ids:
                comp_row = store._conn.execute(
                    "SELECT updated_at FROM facts WHERE fact_id = ?", (comp_id,)
                ).fetchone()
                if comp_row and comp_row["updated_at"]:
                    components[comp_id] = {"updated_at": comp_row["updated_at"]}

        stale = detect_staleness(synthesis, components)
        if stale is None or stale is False:
            continue

        # Fetch component details for synthesis
        comp_facts = []
        with store._lock:
            for comp_id in component_ids:
                comp_row = store._conn.execute(
                    "SELECT fact_id, content, trust_score, updated_at, tags "
                    "FROM facts WHERE fact_id = ?", (comp_id,)
                ).fetchone()
                if comp_row:
                    comp_facts.append(dict(comp_row))

        if not comp_facts:
            failures.append(fact_id)
            continue

        try:
            new_content = synthesize_fn(comp_facts)
        except Exception:
            failures.append(fact_id)
            continue

        if new_content is None:
            continue

        try:
            refresh_synthesis(store, synthesis, new_content)
        except Exception:
            failures.append(fact_id)
            continue

        refreshed_count += 1
        refreshed_ids.append(fact_id)

    return refreshed_count, refreshed_ids, failures


# =============================================================================
# In-Place Synthesis Refresh (uses MemoryStore.update_fact for HRR + entity)
# =============================================================================

def refresh_synthesis(store, synthesis, new_content):
    """
    Refresh a synthesis fact in-place (same fact_id).

    - Appends prior content as history reference
    - Preserves status:current tag
    - Uses store.update_fact() for content/tags update + entity rebinding
    - Manually recomputes HRR vector (update_fact doesn't recompute HRR)
    - Manually rebuilds the category bank
    """
    prior_snippet = synthesis["content"][:300].replace("\n", " ")
    history_block = f"\n\n[Prior - {synthesis['created_at']}]: {prior_snippet}..."
    final_content = new_content + history_block

    tags_str = synthesis.get("tags", "") or ""
    tag_parts = [t.strip() for t in tags_str.split(",") if t.strip()]
    non_status = [t for t in tag_parts if not t.startswith("status:")]
    if any(t == "status:current" for t in tag_parts):
        non_status.append("status:current")
    final_tags = ",".join(non_status)

    fact_id = synthesis["fact_id"]
    category = synthesis.get("category", "general")

    # Step 1: update content + tags + entity links
    store.update_fact(fact_id=fact_id, content=final_content, tags=final_tags)

    # Step 2: recompute HRR vector (update_fact doesn't do this)
    store._compute_hrr_vector(fact_id, final_content)

    # Step 3: rebuild the category bank so HRR changes take effect
    store._rebuild_bank(category)


# =============================================================================
# Fact Collection
# =============================================================================

def collect_reliable_facts(store, min_trust=0.5):
    """
    Collect all reliable facts (trust >= min_trust) for the pipeline.
    Excludes archived facts.

    Args:
        store: MemoryStore instance

    Returns:
        list of fact dicts with 'entities' extracted from content
    """
    with store._lock:
        rows = store._conn.execute("""
            SELECT fact_id, content, trust_score, updated_at, category, tags
            FROM facts
            WHERE trust_score >= ?
              AND (tags IS NULL OR tags NOT LIKE '%status:archived%')
        """, (min_trust,)).fetchall()

    facts = []
    for row in rows:
        fact = dict(row)
        fact["entities"] = store._extract_entities(fact.get("content", ""))
        facts.append(fact)
    return facts


def collect_sessions(entity_stats):
    """
    Placeholder for session collection. Called by agent with session_search results.
    Returns empty list — agent appends session results.
    """
    return []
