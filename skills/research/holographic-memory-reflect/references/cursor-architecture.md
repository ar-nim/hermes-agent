# Cursor Architecture: File vs DB vs Cron State

## Three Options

| | File | DB fact | Cron `last_run_at` |
|---|---|---|---|
| Survives job deletion | ✅ | ❌ | ❌ |
| Human inspectable | ✅ | ❌ | ❌ |
| No coupling to external system | ✅ | ✅ | ❌ |

**File wins.** DB facts are for claims, not infrastructure state. Cron `last_run_at` is tied to job lifecycle.

## Script

`<skill_dir>/scripts/holographic_cursor.sh` — resolves to:
`$HERMES_HOME/skills/holographic-memory/holographic-memory-reflect/scripts/holographic_cursor.sh`

```sh
# Read — empty output means first run (7-day window)
holographic_cursor.sh read

# Write — UTC ISO timestamp
holographic_cursor.sh write "<UTC-ISO-timestamp>"
```

**Always `chmod +x` at creation** — avoids per-call permission prompts from `terminal()` tool.

## When NOT file-based

- Multi-process concurrent reads → DB
- Secrets / credentials → secrets manager
- Transactional state → DB

## Terminal + Cursor Script: Known Failure Mode

The cursor script uses `HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}` to resolve the cursor path. When called via `terminal()` tool, HERMES_HOME is NOT exported to the subprocess environment — the script falls back to `$HOME/.hermes`, producing a wrong nested path.

**Symptom:**
```
$HERMES_HOME/.hermes/home/.hermes/skills/.../holographic_cursor.sh: No such file or directory
```

**Root cause:** When HERMES_HOME is absent from the subprocess environment, the bash fallback resolves `$HOME` to `$HERMES_HOME/.hermes`, then the script appends its own `home/.hermes` prefix — creating a phantom `$HERMES_HOME/.hermes/home/.hermes/` path.

**Fix (always works):** Use Python file I/O via `execute_code`:
```python
from pathlib import Path
from datetime import datetime, timezone

cursor_file = Path(hermes_home) / "holographic_memory_cursor"
with open(cursor_file, "w") as f:
    f.write(datetime.now(timezone.utc).isoformat() + "\n")
```

The script itself is correct. The `terminal()` tool does not pass HERMES_HOME into the subprocess. SKILL.md examples use `terminal(command='<skill_dir>/scripts/...')` as canonical form, but fall back to Python file I/O when that fails.
