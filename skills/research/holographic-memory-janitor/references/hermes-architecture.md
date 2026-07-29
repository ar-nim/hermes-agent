# Hermes Agent Architecture — Janitor Context

Essential facts about the Hermes Agent memory system, relevant to planning cleaning passes and understanding why certain patterns exist.

## SOUL.md vs. MEMORY

| | SOUL.md | MEMORY |
|---|---|---|
| Path | `~/.hermes/SOUL.md` | `~/.hermes/memories/MEMORY.md` |
| Role | Agent identity + behavioral directives | Persistent facts about user/environment |
| Injection | Slot #1 of system prompt, every turn | Frozen snapshot at session start |
| Mid-session writes | Visible next turn | File updated, snapshot NOT — invisible to current session |
| Limit | No hard limit | 2,200 chars |
| Edit propagation | Next turn | Next session restart |

**Behavioral directives** (e.g., which memory discipline is active) belong in SOUL.md. Putting them in MEMORY causes staleness.

## Memory Tool (memory_tool)

- The tool is named `memory` with `target="memory"` or `target="user"`, NOT `fact_store`.
- `fact_store` is a different tool with different capabilities (HRR algebra, trust scoring, contradiction scans).
- The `memory_tool` schema is defined in `tools/memory_tool.py` and has no `fact_feedback` action.
- `MEMORY_GUIDANCE` in `agent/prompt_builder.py` is the system constant that tells the agent how to use the memory tool — it is NOT user-editable; user directives go in SOUL.md.

## Fact Store (fact_store)

- Separate from `memory_tool`. Has `add`, `search`, `probe`, `reason`, `contradict`, `remove` actions.
- New facts start at trust_score 0.5. `fact_feedback(action='helpful', ...)` adds +0.05.
- `min_trust_threshold` default: 0.3. Facts below this are hidden from `search`/`probe` but NOT auto-deleted — must be hard-removed with `fact_store(action='remove')`.
- `contradict` takes only `category` param (no `query`). Returns pairs above 0.3 contradiction threshold.
- `list` has no `offset` or `tags` filter — top-N recent only.

## Skill System

- Skill index is built at session start via `build_skills_system_prompt()` and cached (in-process LRU + disk snapshot keyed by mtime/size manifest).
- Skills are NOT auto-triggered on tool calls. The agent sees the index and calls `skill_view(name)` when it deems relevant.
- Skill frontmatter supports: `fallback_for_toolsets`, `fallback_for_tools`, `requires_toolsets`, `requires_tools` — these control whether a skill appears in the index at all.
- No `required_skills` or `always_active` field exists. A skill must be explicitly called.
- Overlapping triggers: no "first match wins" — agent sees all matching skills simultaneously.

## Snapshot Model

```python
# From tools/memory_tool.py
class MemoryStore:
    # Frozen at load time — used for system prompt injection
    _system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

    # Live state — mutated by tool calls, persisted to disk
    memory_entries: List[str] = []
    user_entries: List[str] = []
```

Mid-session `memory_tool(action='add')` writes update the files and the live state. The frozen `_system_prompt_snapshot` is what actually gets injected into the system prompt. Mid-session writes are invisible to the current session's system prompt.

**Cleaning implication:** If MEMORY.md contains stale entries, editing the file won't help the current session — only the next one. The janitor cleans the file; awareness of what the current session actually sees requires understanding the snapshot model.
