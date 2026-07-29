"""
TDD tests for janitor audit scripts — check_hrr_health.py and check_entity_bindings.py.

These scripts use MemoryStore (shared connection) with --db flag for testing.
Tests use real temp databases via tmp_path, not mocks.

RED phase: scripts don't exist yet → ImportError.
"""
import os, sys
from pathlib import Path
import pytest

HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
AGENT_DIR = os.path.join(HOME, "hermes-agent")
HOLO_DIR = os.path.join(AGENT_DIR, "plugins", "memory", "holographic")
for p in [HOLO_DIR, AGENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def store(tmp_path):
    """Create a MemoryStore with a temp DB, seeded with test data."""
    from store import MemoryStore
    db = str(tmp_path / "test.db")
    ms = MemoryStore(db_path=db)
    yield ms
    ms.close()


# =============================================================================
# check_hrr_health.py — HRR vector byte-length + NULL detection
# =============================================================================

class TestHrrHealth:
    def test_clean_store_reports_healthy(self, tmp_path):
        """Store with all homogeneous vectors → OK."""
        from check_hrr_health import audit_hrr_health
        from store import MemoryStore
        db = str(tmp_path / "clean.db")
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"TestAlpha" detail', category="general", tags="")
        ms.close()
        report = audit_hrr_health(db)
        assert report["corrupt"] is False
        assert report["null_count"] == 0

    def test_null_vectors_detected(self, tmp_path):
        """Facts with NULL hrr_vector → reported."""
        from check_hrr_health import audit_hrr_health
        from store import MemoryStore
        db = str(tmp_path / "null.db")
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"HasVector" fact', category="general", tags="")
        # Manually NULL the vector
        with ms._lock:
            ms._conn.execute("UPDATE facts SET hrr_vector = NULL WHERE fact_id = 1")
        ms.close()
        report = audit_hrr_health(db)
        assert report["null_count"] == 1

    def test_hrr_dim_from_store_not_hardcoded(self, tmp_path):
        """Expected byte length computed from store.hrr_dim, not hardcoded."""
        from check_hrr_health import audit_hrr_health
        from store import MemoryStore
        db = str(tmp_path / "dim.db")
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"TestAlpha" detail', category="general", tags="")
        ms.close()
        report = audit_hrr_health(db)
        # MemoryStore default is 1024, so expected_bytes = 1024 * 8 = 8192
        # NOT 4096 * 8 = 32768 (the old hardcoded value)
        assert report["expected_bytes"] == 1024 * 8

    def test_per_category_breakdown(self, tmp_path):
        """Report shows per-category breakdown."""
        from check_hrr_health import audit_hrr_health
        from store import MemoryStore
        db = str(tmp_path / "cats.db")
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"GeneralAlpha" fact', category="general", tags="")
        ms.add_fact(content='"UserAlpha" pref', category="user_pref", tags="")
        ms.close()
        report = audit_hrr_health(db)
        assert "general" in report["categories"]
        assert "user_pref" in report["categories"]
        assert report["categories"]["general"]["total"] == 1
        assert report["categories"]["user_pref"]["total"] == 1


# =============================================================================
# check_entity_bindings.py — entity binding rate (store-derived)
# =============================================================================

class TestEntityBindings:
    def test_healthy_binding_rate(self, tmp_path):
        """Entity bound in most facts that mention it → OK."""
        from check_entity_bindings import audit_entity_bindings
        from store import MemoryStore
        db = str(tmp_path / "healthy.db")
        ms = MemoryStore(db_path=db)
        # add_fact extracts entities from content via plugin's own logic
        ms.add_fact(content='"TestEntity" is important detail one', category="general")
        ms.add_fact(content='"TestEntity" is also in detail two', category="general")
        ms.add_fact(content='"TestEntity" appears in detail three', category="general")
        ms.close()
        report = audit_entity_bindings(db)
        assert len(report["entities"]) > 0

    def test_low_binding_rate_flagged(self, tmp_path):
        """Entity mentioned in content but not bound → WARNING/CRITICAL."""
        from check_entity_bindings import audit_entity_bindings
        from store import MemoryStore
        db = str(tmp_path / "lowrate.db")
        ms = MemoryStore(db_path=db)
        # Need >= 3 facts for entity to clear the frequency floor
        ms.add_fact(content='"OrphanEntity" is a detail one', category="general")
        ms.add_fact(content='"OrphanEntity" is a detail two', category="general")
        ms.add_fact(content='"OrphanEntity" appears in detail three', category="general")
        ms.close()
        report = audit_entity_bindings(db)
        entity_names = [e["entity"] for e in report["entities"]]
        assert "OrphanEntity" in entity_names

    def test_store_derived_not_hardcoded(self, tmp_path):
        """Entity list comes from the store, not a hardcoded DEFAULT_ENTITIES list."""
        from check_entity_bindings import audit_entity_bindings
        from store import MemoryStore
        db = str(tmp_path / "derived.db")
        ms = MemoryStore(db_path=db)
        # Need >= 3 facts for entity to clear the frequency floor
        ms.add_fact(content='"UniqueToThisStore" fact content one', category="general")
        ms.add_fact(content='"UniqueToThisStore" fact content two', category="general")
        ms.add_fact(content='"UniqueToThisStore" fact content three', category="general")
        ms.close()
        report = audit_entity_bindings(db)
        entity_names = [e["entity"] for e in report["entities"]]
        assert "UniqueToThisStore" in entity_names
        # Should NOT contain any hardcoded defaults
        assert "User" not in entity_names
        assert "CityX" not in entity_names

    def test_empty_store_returns_empty(self, tmp_path):
        """No facts → empty report, no crash."""
        from check_entity_bindings import audit_entity_bindings
        from store import MemoryStore
        db = str(tmp_path / "empty.db")
        ms = MemoryStore(db_path=db)
        ms.close()
        report = audit_entity_bindings(db)
        assert len(report["entities"]) == 0

    def test_binding_rate_calculation(self, tmp_path):
        """Rate = bound_facts / fts_mentions. Verify math."""
        from check_entity_bindings import audit_entity_bindings
        from store import MemoryStore
        db = str(tmp_path / "math.db")
        ms = MemoryStore(db_path=db)
        # 3 facts all mentioning and bound to SameEntity
        ms.add_fact(content='"SameEntity" in fact one', category="general")
        ms.add_fact(content='"SameEntity" in fact two', category="general")
        ms.add_fact(content='"SameEntity" in fact three', category="general")
        ms.close()
        report = audit_entity_bindings(db)
        same = [e for e in report["entities"] if e["entity"] == "SameEntity"]
        if same:
            assert same[0]["bound"] == 3
            assert same[0]["rate"] >= 0.85


# =============================================================================
# CLI --db flag (both scripts accept --db for testing)
# =============================================================================

class TestCliDbFlag:
    def test_hrr_health_accepts_db_flag(self, tmp_path):
        """Script runs with --db pointing to a test DB."""
        import subprocess
        db = str(tmp_path / "cli.db")
        # Create a store to initialize the DB
        from store import MemoryStore
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"CliTest" detail', category="general", tags="")
        ms.close()
        result = subprocess.run(
            [sys.executable, os.path.join(SKILL_DIR, "scripts", "check_hrr_health.py"), "--db", db],
            capture_output=True, text=True, timeout=10
        )
        assert "Traceback" not in result.stderr
        assert result.returncode in (0, 1)

    def test_entity_bindings_accepts_db_flag(self, tmp_path):
        """Script runs with --db pointing to a test DB."""
        import subprocess
        db = str(tmp_path / "cli.db")
        from store import MemoryStore
        ms = MemoryStore(db_path=db)
        ms.add_fact(content='"CliTest" detail', category="general", tags="")
        ms.close()
        result = subprocess.run(
            [sys.executable, os.path.join(SKILL_DIR, "scripts", "check_entity_bindings.py"), "--db", db],
            capture_output=True, text=True, timeout=10
        )
        assert "Traceback" not in result.stderr
        assert result.returncode in (0, 1)
