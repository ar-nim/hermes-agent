"""
TDD tests for reflect_pipeline.py — DB-coupled code using MemoryStore.

These tests use REAL databases (tmp_path), not mocks. This follows the TDD
principle: test real behavior, not mock interactions.

RED phase: module doesn't exist yet → ImportError.
"""
import os, sys
from pathlib import Path
import pytest

# Ensure MemoryStore is importable (needs hermes-agent root + holographic plugin)
HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
AGENT_DIR = os.path.join(HOME, "hermes-agent")
HOLO_DIR = os.path.join(AGENT_DIR, "plugins", "memory", "holographic")
for p in [HOLO_DIR, AGENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


# =============================================================================
# HELPER: Create a MemoryStore with a fresh temp DB
# =============================================================================

@pytest.fixture
def store(tmp_path):
    """Create a MemoryStore with a temp DB for testing."""
    from store import MemoryStore
    db = str(tmp_path / "test.db")
    ms = MemoryStore(db_path=db)
    yield ms
    ms.close()


# =============================================================================
# get_store — MemoryStore factory
# =============================================================================

class TestGetStore:
    def test_returns_memory_store_with_correct_db(self):
        from reflect_pipeline import get_store
        from store import MemoryStore
        db = "/tmp/test_get_store.db"
        ms = get_store(db)
        try:
            assert isinstance(ms, MemoryStore)
            assert str(ms.db_path) == db
        finally:
            ms.close()
            if os.path.exists(db):
                os.unlink(db)

    def test_hrr_dim_from_store_not_hardcoded(self):
        """hrr_dim must come from MemoryStore, not hardcoded 4096."""
        from reflect_pipeline import get_store
        db = "/tmp/test_hrr_dim.db"
        ms = get_store(db)
        try:
            assert ms.hrr_dim == 1024
        finally:
            ms.close()
            if os.path.exists(db):
                os.unlink(db)


# =============================================================================
# collect_reliable_facts — fact collection with trust threshold
# =============================================================================

class TestCollectReliableFacts:
    def test_returns_facts_above_trust_threshold(self, store):
        from reflect_pipeline import collect_reliable_facts
        fid1 = store.add_fact(content='"HighTrust" fact', category="general",
                              tags="")
        fid2 = store.add_fact(content='"LowTrust" fact', category="general",
                              tags="")
        # Set trust via direct SQL (add_fact doesn't accept trust_delta)
        with store._lock:
            store._conn.execute("UPDATE facts SET trust_score = 0.8 WHERE fact_id = ?", (fid1,))
            store._conn.execute("UPDATE facts SET trust_score = 0.2 WHERE fact_id = ?", (fid2,))
        facts = collect_reliable_facts(store, min_trust=0.5)
        assert len(facts) == 1
        assert "HighTrust" in facts[0]["content"]

    def test_excludes_archived_facts(self, store):
        from reflect_pipeline import collect_reliable_facts
        fid1 = store.add_fact(content='"Active" fact', category="general",
                              tags="")
        fid2 = store.add_fact(content='"Archived" fact', category="general",
                              tags="status:archived")
        with store._lock:
            store._conn.execute("UPDATE facts SET trust_score = 0.8 WHERE fact_id = ?", (fid1,))
            store._conn.execute("UPDATE facts SET trust_score = 0.8 WHERE fact_id = ?", (fid2,))
        facts = collect_reliable_facts(store, min_trust=0.5)
        assert len(facts) == 1
        assert "Active" in facts[0]["content"]


# =============================================================================
# execute_step0 — stale synthesis detection + refresh
# =============================================================================

class TestExecuteStep0:
    def test_detects_and_refreshes_stale_synthesis(self, tmp_path):
        """Component updated after synthesis creation → stale → refresh."""
        from store import MemoryStore
        from reflect_pipeline import execute_step0

        db = str(tmp_path / "stale.db")
        ms = MemoryStore(db_path=db)
        try:
            # Add component and synthesis
            ms.add_fact(content='"CompAlpha" detail', category="general",
                        tags="source")
            ms.add_fact(content='Synth about "CompAlpha"', category="general",
                        tags="status:current,type:synthesis,components:1")
            # Backdate synthesis, update component to be newer
            with ms._lock:
                ms._conn.execute(
                    "UPDATE facts SET created_at = '2026-01-01T00:00:00+00:00' WHERE fact_id = 2"
                )
                ms._conn.execute(
                    "UPDATE facts SET updated_at = '2026-06-01T00:00:00+00:00' WHERE fact_id = 1"
                )

            def synthesize(facts):
                return "Refreshed synthesis content"

            count, ids, failures = execute_step0(ms, synthesize)
            assert count == 1, f"Expected 1, got {count}"
            assert 2 in ids
            assert failures == []
        finally:
            ms.close()

    def test_skips_current_synthesis(self, tmp_path):
        """Component older than synthesis → not stale → no refresh."""
        from store import MemoryStore
        from reflect_pipeline import execute_step0

        db = str(tmp_path / "current.db")
        ms = MemoryStore(db_path=db)
        try:
            ms.add_fact(content='"CompAlpha" detail', category="general",
                        tags="source")
            ms.add_fact(content='Synth about "CompAlpha"', category="general",
                        tags="status:current,type:synthesis,components:1")
            # Synthesis AFTER component → current
            with ms._lock:
                ms._conn.execute(
                    "UPDATE facts SET created_at = '2026-06-01T00:00:00+00:00' WHERE fact_id = 2"
                )
                ms._conn.execute(
                    "UPDATE facts SET updated_at = '2026-01-01T00:00:00+00:00' WHERE fact_id = 1"
                )

            count, ids, failures = execute_step0(ms, lambda f: "new")
            assert count == 0
        finally:
            ms.close()

    def test_preserves_status_current_tag(self, tmp_path):
        """After refresh, status:current must still be in tags."""
        from store import MemoryStore
        from reflect_pipeline import execute_step0

        db = str(tmp_path / "tags.db")
        ms = MemoryStore(db_path=db)
        try:
            ms.add_fact(content='"CompAlpha" detail', category="general",
                        tags="source")
            ms.add_fact(content='Old synth', category="general",
                        tags="status:current,type:synthesis,components:1")
            with ms._lock:
                ms._conn.execute(
                    "UPDATE facts SET created_at = '2026-01-01T00:00:00+00:00' WHERE fact_id = 2"
                )
                ms._conn.execute(
                    "UPDATE facts SET updated_at = '2026-06-01T00:00:00+00:00' WHERE fact_id = 1"
                )

            execute_step0(ms, lambda f: "New content")

            with ms._lock:
                row = ms._conn.execute(
                    "SELECT tags FROM facts WHERE fact_id = 2"
                ).fetchone()
            assert "status:current" in row["tags"]
        finally:
            ms.close()


# =============================================================================
# refresh_synthesis — in-place synthesis update
# =============================================================================

class TestRefreshSynthesis:
    def test_keeps_same_fact_id(self, store):
        from reflect_pipeline import refresh_synthesis
        store.add_fact(content='Old synthesis content', category="general",
                       tags="status:current,type:synthesis")
        synthesis = {
            "fact_id": 1,
            "content": "Old synthesis content",
            "created_at": "2026-01-01T00:00:00+00:00",
            "tags": "status:current,type:synthesis",
        }
        refresh_synthesis(store, synthesis, "New synthesis content")
        with store._lock:
            row = store._conn.execute(
                "SELECT fact_id, content FROM facts WHERE fact_id = 1"
            ).fetchone()
        assert row["fact_id"] == 1
        assert "New synthesis content" in row["content"]

    def test_prior_content_appended_as_history(self, store):
        from reflect_pipeline import refresh_synthesis
        store.add_fact(content='Original plan at LocationX', category="general",
                       tags="status:current,type:synthesis")
        synthesis = {
            "fact_id": 1,
            "content": "Original plan at LocationX",
            "created_at": "2026-01-01T00:00:00+00:00",
            "tags": "status:current,type:synthesis",
        }
        refresh_synthesis(store, synthesis, "Updated plan")
        with store._lock:
            row = store._conn.execute(
                "SELECT content FROM facts WHERE fact_id = 1"
            ).fetchone()
        assert "Original plan" in row["content"]
        assert "LocationX" in row["content"]

    def test_status_current_preserved(self, store):
        from reflect_pipeline import refresh_synthesis
        store.add_fact(content='Old content', category="general",
                       tags="status:current,type:synthesis,components:5")
        synthesis = {
            "fact_id": 1,
            "content": "Old content",
            "created_at": "2026-01-01T00:00:00+00:00",
            "tags": "status:current,type:synthesis,components:5",
        }
        refresh_synthesis(store, synthesis, "New content")
        with store._lock:
            row = store._conn.execute(
                "SELECT tags FROM facts WHERE fact_id = 1"
            ).fetchone()
        assert "status:current" in row["tags"]
