# Source Entities Phantom Entity Bug

## What It Is

The reflect pipeline appends a metadata suffix to synthesis facts:

```
content: "...claim about an entity... | Source Entities: "EntityA", "EntityB""
```

The suffix is stored as part of `content`. When `_extract_entities()` runs (on write or
update), the quoted names inside the suffix are extracted as entities — but they're
metadata, not actual content.

## How It Creates Phantom Entities

1. Reflect writes a synthesis fact with `| Source Entities: "X", "Y"`
2. The `|` character is a content delimiter, not an entity
3. `_extract_entities()` scans the FULL content including the suffix
4. `"EntityA"` and `"EntityB"` inside the Source Entities clause ARE double-quoted → extracted as phantom entities
5. The entity resolver creates entity records for names that should never be retrieval targets

## Phantom Entities Created (Example)

Example phantom entities created by the artifact suffix:
- `Source Entities` — entity ID 76, linked to 4 facts
- `yes` — entity ID 114, linked to 2 facts
- A long quoted string from synthesis output — linked to 2 facts

All are junk — they have no independent meaning as retrieval targets.

## Detection

```python
c.execute("""
    SELECT fact_id, content FROM facts
    WHERE content LIKE '%| Source Entities: %'
""")
```

Returns all facts with the artifact suffix.

## Fix Procedure

For each affected fact:

1. **Strip suffix** — update content to remove `| Source Entities: ...`  
2. **Delete phantom links** — the entity links created from the suffix are wrong
3. **Re-resolve via update** — `fact_store update` with clean content re-runs `_extract_entities()` and creates correct links

Example:
```
# Before fix:
content = 'EntityX treatment requires... | Source Entities: "EntityX", "EntityY"'

# Step 1: update content (strip suffix)
# Step 2: fact_store update re-resolves entities
# After fix:
content = 'EntityX treatment requires...'
# Correct entities "EntityX" and "EntityY" are extracted from actual content
# No phantom "Source Entities" entity created
```

## Prevention

The Reflect skill should strip the Source Entities suffix before writing synthesis facts
to the store. Until that's fixed, the janitor catches it in Pass 1 as a known artifact pattern.

**General rule:** When a synthesis skill appends metadata to fact content, that metadata
belongs in the skill's internal state, not in the fact store's content field.
