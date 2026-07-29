# Reflect Pipeline Lessons

## What Failed

### Cursor in DB violates Principle 1
Storing `holographic_memory_reflect last_run` as a fact in the fact store is bookkeeping metadata — exactly what Principle 1 forbids. The fact store is for claims, not infrastructure state.
- **Fix**: Cursor moved to `<skill_dir>/scripts/holographic_cursor.sh` — profile-aware via HERMES_HOME, plain ISO timestamp file, human-inspectable, survives job deletion

### Cron last_run_at is redundant and fragile
Controlled by the cron system, not by the reflect skill. Redundant with reflect's own cursor. Lost if job is deleted/recreated.
- **Fix**: Reflect owns its cursor exclusively. Cron's last_run_at is ignored.

### deliver=origin output routing unclear
Cron ran (last_status: ok) but output may not have reached the originating chat. Cron runs in an isolated sub-session.
- **Implication**: Don't rely on cron output reaching the user chat. Verify delivery separately.

## What Worked

### File-based cursor is robust
`echo "<ISO>" > ~/.hermes/holographic_memory_cursor` — survives anything. Human can `cat` to inspect at any time.

### Cron repeat=0 is a one-shot, not bootstrap
`cronjob run job_id=xxx repeat=0` fires the existing job outside its schedule. The job's own `repeat: forever` handles recurrence. Do not conflate manual trigger with job creation.

## What Must Not Be Saved

### #7 — Duplicate facts are janitor's job
Fact store had duplicate fact IDs for the same claims (Core leaders 35/78, Wisdom room 45/79, etc.). This is a janitor-class issue, not a reflect lesson. Janitor should catch these — reflect should not reason about its own deduplication.

## Schedule

Daily at 22:00 local time — cron job `<cron-id>`
