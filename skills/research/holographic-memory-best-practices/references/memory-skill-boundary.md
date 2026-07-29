# Memory vs. Skills — Boundary Discipline

## When Memory Is Wrong

Holographic memory isEpisodic — it stores "what is true about this user." Skills are Procedural — they store "how to do this class of task." A fact can be in the wrong system even when the content is correct.

**Memory-skill redundancy:** Fact 254 ("auto-detect day type from `date`") was correct — the agent should do this. But the `city-metro` skill already encodes the exact same behavior as a procedure. Storing it as a fact creates a mirror that can drift from the skill over time.

**Memory teaching wrong behavior:** Fact 256 ("trust conversation header as authoritative for date/day") was actively harmful — `holographic-memory-best-practices` Pitfall 29 explicitly corrects this pattern. The skill was right; the memory was wrong. Memory that teaches behavior must be consistent with the skill that governs that behavior.

## The Ownership Test

Ask: **"Is this primarily a fact about the user, or a fact about how the system works?"**

| Fact type | Owner | Example |
|-----------|-------|---------|
| Who the user is | Memory | e.g. salaried professional, chronic health condition (ConditionA), partnered — generic template row; substitute the actual user's profile |
| What the user cares about | Memory | Data rigor > freshness, proactive accountability |
| What the user did (confirmed) | Memory | Trip on a scheduled date, event budget (significant amount) |
| How the system works | Skill | City rail auto-detects day type, MedicationB watchdog pattern |
| Tool configuration | Skill | CityBus GTFS URL, NationalWeatherAPI endpoint |
| Cron/job architecture | Skill | Morning watchdog, evening watchdog pattern |
| Procedure or workflow | Skill | departure check sequence, MedicationB logging protocol |

## Memory-Skill Interaction Patterns

### Pattern 1: Skill owns the procedure; memory optionally owns the instance

**Example:** MedicationB departure check
- Skill (`health-monitoring`): "Before leaving home, query habit tracker, if not logged → remind"
- Memory (fact 321): "User takes MedicationB daily, check if logged before leaving home"

Both exist. Skill is authoritative for sequence; memory is a lightweight reminder that the pattern exists.

### Pattern 2: Skill owns it entirely; memory should not duplicate

**Example:** CityBus GTFS URL
- Skill (`citybus`): has the URL and freshness-check logic
- Memory (old fact 278): just the URL string

Delete from memory. The skill is the authoritative source. If the URL changes, the skill gets updated — memory becomes stale.

### Pattern 3: Memory teaches wrong behavior; skill corrects it

**Example:** Fact 256 vs. `holographic-memory-best-practices` Pitfall 29
- Memory said: "trust conversation header"
- Skill says: "cross-check, user's stated date overrides header"

When this conflict is found: delete the memory fact. The skill is the living discipline; the memory was a static snapshot that became wrong.

## The Cleanup Trigger

During janitor passes or explicit memory review, for every fact ask:
1. Is this a confirmed personal pattern about User? → keep in memory
2. Is this describing tool behavior, API URLs, cron IDs, or procedural sequences? → delete from memory (skill owns it)
3. Is this a confirmed personal pattern AND a skill also encodes the procedure? → both can coexist (instance + method)
4. Does this contradict an existing skill? → delete from memory immediately

## Session Log

Cleanup executed:
- Removed 254, 256, 278, 282, 288, 322, 447 (skill-redundant)
- Removed 467-477 (seed anchors — system tuning, not episodic facts)
- Removed 304, 305, 306, 426, 432, 433, 461, 479, 485, 495, 400, 431, 459 (stale artifacts)
- Preserved 331, 335, 337, 343, 392, 393 (personal biographical facts)
- Removed 289 (Joplin not set up — tool fact, not a user fact)