"""
reflect_logic.py — Pure functions for the reflect pipeline.

No database imports, no side effects. These functions define the deterministic
behavior of the reflect pipeline: window calculation, entity classification,
staleness detection, session deduplication, and budget planning.

The agent (or cron-driven scripts) calls these functions for computation and
uses fact_store / MemoryStore for persistence.
"""
import re
from datetime import datetime, timezone


# =============================================================================
# Adaptive Window
# =============================================================================

def compute_window(fact_span_days):
    """Compute session history search window. Clamped between 7 and 30 days."""
    return min(30, max(7, fact_span_days + 5))


# =============================================================================
# Entity Temporal Classification
# =============================================================================

def classify_entity_temporal(mention_count, timespan_days):
    """Classify entity as long-term or short-term based on mention frequency."""
    if mention_count >= 3:
        return "long-term"
    if mention_count >= 2 and timespan_days >= 7:
        return "long-term"
    return "short-term"


# =============================================================================
# Entity Stats Computation
# =============================================================================

def _parse_dt(value):
    """Parse datetime from ISO string. Returns UTC-aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_entity_stats(facts):
    """Compute per-entity mention counts and timespans from a list of facts."""
    entity_data = {}
    for fact in facts:
        entities = fact.get("entities", [])
        ts_str = fact.get("updated_at", "")
        if not ts_str:
            continue
        try:
            dt = _parse_dt(ts_str)
        except (ValueError, AttributeError):
            continue
        for entity in entities:
            if entity not in entity_data:
                entity_data[entity] = {"count": 0, "dates": []}
            entity_data[entity]["count"] += 1
            entity_data[entity]["dates"].append(dt)
    result = {}
    for entity, data in entity_data.items():
        dates = sorted(data["dates"])
        timespan_days = (dates[-1] - dates[0]).days if len(dates) >= 2 else 0
        result[entity] = {"count": data["count"], "timespan_days": timespan_days}
    return result


# =============================================================================
# Staleness Detection
# =============================================================================

def detect_staleness(synthesis, components):
    """
    Determine if a synthesis is stale.
    Returns True (stale), False (current), or None (cannot determine).
    """
    component_ids = synthesis.get("components", [])
    if not component_ids:
        return None
    created_str = synthesis.get("created_at", "")
    if not created_str:
        return None
    created_dt = _parse_dt(created_str)
    for comp_id in component_ids:
        comp_data = components.get(comp_id)
        if comp_data is None:
            return None
        comp_ts = comp_data.get("updated_at")
        if not comp_ts:
            continue
        comp_dt = _parse_dt(comp_ts)
        if comp_dt > created_dt:
            return True
    return False


# =============================================================================
# Session Deduplication
# =============================================================================

def deduplicate_sessions(sessions):
    """Deduplicate by session_id, preserving order of first occurrence."""
    seen = set()
    result = []
    for s in sessions:
        sid = s.get("session_id")
        if sid and sid not in seen:
            seen.add(sid)
            result.append(s)
    return result


# =============================================================================
# Deep Session Pass Budget
# =============================================================================

def plan_deep_session_calls(long_term_entities, limit_per_entity=2, max_entities=5):
    """Plan deep session search calls. Capped at max_entities."""
    return [(e, limit_per_entity) for e in long_term_entities[:max_entities]]
