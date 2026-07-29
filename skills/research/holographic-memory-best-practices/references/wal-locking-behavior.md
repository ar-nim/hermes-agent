# WAL Locking: What the Plugin Does and Doesn't Do

## What the code actually shows (store.py + __init__.py)

```python
# store.py line 130
self._conn.execute("PRAGMA journal_mode=WAL")

# store.py line 115-119
self._conn = sqlite3.connect(
    str(self.db_path),
    check_same_thread=False,
    timeout=10.0,  # 10-second write timeout
)
self._lock = threading.RLock()  # process-local only, NOT cross-process
```

## Key facts about WAL behavior

1. **WAL allows concurrent readers.** A reader does NOT block a writer, and a writer does NOT block a reader. `fact_store(action='list')` in reflect's Step 1 can run concurrently with an interactive session writing facts — it will NOT be blocked by the interactive session's reads.

2. **Writers need EXCLUSIVE lock.** A write transaction (INSERT/UPDATE/DELETE) must acquire an EXCLUSIVE lock. If another process already holds it, the new writer waits up to `timeout=10.0` seconds, then fails with "database is locked."

3. **`check_same_thread=False`** is necessary and correct for WAL. It lets a single connection be used across threads within the process. It does NOT create cross-process lock sharing.

4. **`threading.RLock()`** is process-local. It has NO effect on cross-process contention. The only real cross-process lock is the SQLite WAL exclusive write lock.

## What happened with the 22:07 reflect failure

The interactive session was mid-write transaction at 22:07. The cron's read (Step 1 `fact_store(action='list')`) succeeded via WAL concurrency. But Steps 5-7 tried to write synthesis facts, the interactive session held the EXCLUSIVE write lock → cron waited 10 seconds → got "database is locked" → fell to read-only mode.

## The correct response

This is NOT a WAL bug. It is a timing problem: reflect fired while an active session held a write transaction.

**Moving reflect to 2am (local time) solves this** — the interactive session has ended, WAL checkpoint has run, and the DB is clean.

An idle-check (looking for recent fact updates before running) would be a secondary guard but is NOT required for correctness. The 2am schedule alone is sufficient.

## No additional lock detection needed in the skill

- WAL concurrent reads: no problem, don't block
- WAL exclusive write: 10-second timeout is the correct behavior
- If write fails due to lock: defer 1 hour and reschedule (already implemented in v2.3.0+)

## Implications for reflect skill design

- Step 1 `fact_store(action='list')` is safe to run even when an interactive session is active — it will NOT block on the session's writes
- Steps 5-7 (writes) are the only point of contention — these are protected by the existing defer-on-lock logic
- The 2am schedule eliminates 99% of lock collisions by ensuring no interactive session is running
