"""
TDD tests for reflect_logic.py — pure functions, zero DB imports.
These tests define BEHAVIOR, not implementation. The module doesn't exist yet.
RED phase: all tests fail with ImportError.
"""
import pytest
from datetime import datetime, timezone, timedelta


# =============================================================================
# compute_window — adaptive session history search window
# =============================================================================

class TestAdaptiveWindow:
    def test_window_grows_with_fact_timespan(self):
        from reflect_logic import compute_window
        assert compute_window(fact_span_days=3) > 7

    def test_window_caps_at_30_days(self):
        from reflect_logic import compute_window
        assert compute_window(fact_span_days=100) <= 30

    def test_window_never_below_7_days(self):
        from reflect_logic import compute_window
        assert compute_window(fact_span_days=0) >= 7

    def test_window_for_slow_moving_topic(self):
        from reflect_logic import compute_window
        assert 20 <= compute_window(fact_span_days=25) <= 30


# =============================================================================
# classify_entity_temporal — long-term vs short-term entity classification
# =============================================================================

class TestEntityTemporalClassification:
    def test_single_mention_is_short_term(self):
        from reflect_logic import classify_entity_temporal
        assert classify_entity_temporal(mention_count=1, timespan_days=0) == "short-term"

    def test_three_mentions_is_long_term(self):
        from reflect_logic import classify_entity_temporal
        assert classify_entity_temporal(mention_count=3, timespan_days=2) == "long-term"

    def test_two_mentions_over_two_weeks_is_long_term(self):
        from reflect_logic import classify_entity_temporal
        assert classify_entity_temporal(mention_count=2, timespan_days=14) == "long-term"

    def test_two_mentions_within_week_is_short_term(self):
        from reflect_logic import classify_entity_temporal
        assert classify_entity_temporal(mention_count=2, timespan_days=3) == "short-term"

    def test_five_mentions_in_one_day_is_long_term(self):
        from reflect_logic import classify_entity_temporal
        assert classify_entity_temporal(mention_count=5, timespan_days=0) == "long-term"


# =============================================================================
# compute_entity_stats — per-entity mention counts and timespans
# =============================================================================

class TestEntityStats:
    def test_mentions_counted_per_entity(self):
        from reflect_logic import compute_entity_stats
        facts = [
            {"entities": ["CityX"], "updated_at": "2026-05-01T00:00:00+00:00"},
            {"entities": ["CityX"], "updated_at": "2026-05-05T00:00:00+00:00"},
            {"entities": ["CityX"], "updated_at": "2026-05-10T00:00:00+00:00"},
        ]
        stats = compute_entity_stats(facts)
        assert stats["CityX"]["count"] == 3

    def test_timespan_computed_from_first_to_last(self):
        from reflect_logic import compute_entity_stats
        facts = [
            {"entities": ["X"], "updated_at": "2026-05-01T00:00:00+00:00"},
            {"entities": ["X"], "updated_at": "2026-05-15T00:00:00+00:00"},
        ]
        stats = compute_entity_stats(facts)
        assert stats["X"]["timespan_days"] == 14

    def test_multiple_entities_tracked_separately(self):
        from reflect_logic import compute_entity_stats
        facts = [
            {"entities": ["A", "B"], "updated_at": "2026-05-01T00:00:00+00:00"},
            {"entities": ["A"], "updated_at": "2026-05-05T00:00:00+00:00"},
            {"entities": ["B"], "updated_at": "2026-05-10T00:00:00+00:00"},
        ]
        stats = compute_entity_stats(facts)
        assert stats["A"]["count"] == 2
        assert stats["B"]["count"] == 2
        assert stats["A"]["timespan_days"] == 4
        assert stats["B"]["timespan_days"] == 9

    def test_facts_with_no_entities_ignored(self):
        from reflect_logic import compute_entity_stats
        facts = [
            {"entities": [], "updated_at": "2026-05-01T00:00:00+00:00"},
            {"entities": [], "updated_at": "2026-05-05T00:00:00+00:00"},
        ]
        stats = compute_entity_stats(facts)
        assert len(stats) == 0

    def test_same_day_mentions_timespan_zero(self):
        from reflect_logic import compute_entity_stats
        facts = [
            {"entities": ["Y"], "updated_at": "2026-05-11T08:00:00+00:00"},
            {"entities": ["Y"], "updated_at": "2026-05-11T20:00:00+00:00"},
        ]
        stats = compute_entity_stats(facts)
        assert stats["Y"]["timespan_days"] == 0


# =============================================================================
# detect_staleness — is a synthesis stale relative to its components?
# =============================================================================

class TestStalenessDetection:
    def test_newer_component_means_stale(self):
        from reflect_logic import detect_staleness
        synthesis = {"created_at": "2026-05-01T00:00:00+00:00", "components": [10]}
        components = {10: {"updated_at": "2026-05-10T00:00:00+00:00"}}
        assert detect_staleness(synthesis, components) is True

    def test_older_components_mean_current(self):
        from reflect_logic import detect_staleness
        synthesis = {"created_at": "2026-05-10T00:00:00+00:00", "components": [10, 20]}
        components = {
            10: {"updated_at": "2026-05-01T00:00:00+00:00"},
            20: {"updated_at": "2026-05-02T00:00:00+00:00"},
        }
        assert detect_staleness(synthesis, components) is False

    def test_missing_component_means_unknown(self):
        from reflect_logic import detect_staleness
        synthesis = {"created_at": "2026-05-10T00:00:00+00:00", "components": [99]}
        components = {}
        assert detect_staleness(synthesis, components) is None

    def test_same_timestamp_not_newer(self):
        from reflect_logic import detect_staleness
        synthesis = {"created_at": "2026-05-05T00:00:00+00:00", "components": [10]}
        components = {10: {"updated_at": "2026-05-05T00:00:00+00:00"}}
        assert detect_staleness(synthesis, components) is False

    def test_timezone_aware_comparison(self):
        from reflect_logic import detect_staleness
        synthesis = {"created_at": "2026-05-01T00:00:00+00:00", "components": [10]}
        components = {10: {"updated_at": "2026-05-05T08:00:00+07:00"}}
        assert detect_staleness(synthesis, components) is True


# =============================================================================
# deduplicate_sessions — remove duplicate sessions by session_id
# =============================================================================

class TestSessionDeduplication:
    def test_duplicates_removed(self):
        from reflect_logic import deduplicate_sessions
        sessions = [
            {"session_id": "A", "summary": "first"},
            {"session_id": "B", "summary": "second"},
            {"session_id": "A", "summary": "dup of first"},
        ]
        result = deduplicate_sessions(sessions)
        assert len(result) == 2

    def test_empty_returns_empty(self):
        from reflect_logic import deduplicate_sessions
        assert deduplicate_sessions([]) == []

    def test_all_unique_unchanged(self):
        from reflect_logic import deduplicate_sessions
        sessions = [{"session_id": "A"}, {"session_id": "B"}]
        assert len(deduplicate_sessions(sessions)) == 2


# =============================================================================
# plan_deep_session_calls — budget-capped deep session search planning
# =============================================================================

class TestDeepSessionBudget:
    def test_capped_at_5_entities(self):
        from reflect_logic import plan_deep_session_calls
        entities = ["A", "B", "C", "D", "E", "F", "G"]
        calls = plan_deep_session_calls(entities)
        assert len(calls) <= 5

    def test_returns_entity_limit_pairs(self):
        from reflect_logic import plan_deep_session_calls
        calls = plan_deep_session_calls(["CityX", "MedicationB"])
        assert all(isinstance(c, tuple) and len(c) == 2 for c in calls)

    def test_respects_default_limit_per_entity(self):
        from reflect_logic import plan_deep_session_calls
        calls = plan_deep_session_calls(["CityX"])
        assert calls[0][1] == 2
