# FTS5 Dual-Column Index Trap

## The Problem

The `facts_fts` virtual table is defined with **two** content columns:

```sql
CREATE VIRTUAL TABLE facts_fts
    USING fts5(content, tags, content=facts, content_rowid=fact_id)
```

When you run `SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH 'ConditionA'`, FTS5 searches **both** `content` and `tags` columns. Facts with `ConditionA` in their `tags` field (but not in their `content`) are included in the count.

## Symptom

Anchor monitoring reports bound/total ratio > 1.0 — e.g., InsurerC shows 31 bound but only 30 total in content. The FTS total is inflated by tag-only matches.

For ConditionA specifically:
- `MATCH 'ConditionA'` (all columns): 46 results
- `MATCH 'content:ConditionA'` (content only): 40 results
- 6 facts (#581, #582, #587, plus 3 more) have ConditionA in tags but not content

## Fix

Always use column-specific FTS5 syntax when the virtual table wraps a multi-column table:

```sql
-- WRONG — matches content AND tags
SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH '"ConditionA"'
SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH 'ConditionA'

-- CORRECT — matches content column only
SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH 'content:ConditionA'
```

## Affected Scripts

- `check_anchors.py` — the anchor monitoring script. Use `content:{name}` prefix for column-targeted MATCH.
- Any other FTS5 query against `facts_fts` that doesn't specify `content:` will be inflated.

## Verification Query

```python
c.execute('SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ?', ('ConditionA',))          # all columns
c.execute('SELECT COUNT(*) FROM facts_fts WHERE facts_fts MATCH ?', ('content:ConditionA',))  # content only
# If first > second → cross-column inflation confirmed
```

## Lesson

FTS5 column prefix syntax (`column:value`) is mandatory when the virtual table has multiple content columns. Without it, queries match the union of all indexed columns, not just the intended one.