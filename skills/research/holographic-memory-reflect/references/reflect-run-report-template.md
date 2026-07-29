# Reflect run report — Normal mode

The cron destination expects this exact shape. Fill in every line.
Use ISO date for the run date; the cursor timestamps are full
ISO-8601 with timezone.

```
[REFLECT] Run complete — 2026-06-11
Step 0 (auto-refresh): 0 stale syntheses refreshed (IDs: [])
Step 0 failures: 25  (orphaned components — flag for janitor)
Cursor: 2026-06-09T19:16:29.997113+00:00 -> 2026-06-11T02:00:14.123456+00:00
Window: full corpus
Entity corpus: 466 reliable facts, 946 entities (262 long-term, 684 short-term)
Syntheses written: 4 (IDs: [950, 951, 952, 953])
Contradictions found: 0
Flags for janitor: 25
Next run: tomorrow 02:00 local time
```

## Field guide

- Step 0 (auto-refresh) — count of syntheses actually updated in
  place. With synthesize_fn=None this is always 0. The IDs list
  is the IDs of the syntheses that were refreshed, not the failures.
- Step 0 failures — these are NOT bugs. They are syntheses whose
  component fact_ids no longer resolve (the components were archived
  by the janitor). Surface them in the "Flags for janitor" count.
- Cursor: old -> new — the value before this run and the value
  after. Reflect operates on the full corpus, so the cursor is for
  reporting / scheduling only — it does not constrain the facts
  scanned. The new cursor MUST be later than the old cursor.
- Window: full corpus — always this string. Reflect is not
  windowed. If you ever add a windowed mode, change this line.
- Entity corpus — three numbers from Step 2/3: reliable fact
  count, distinct entity count, and the long/short-term split. The
  long/short split comes from classify_entity_temporal (count >=
  threshold AND timespan >= threshold).
- Syntheses written — the new fact_ids inserted in Step 6. The
  IDs MUST be the ones from the INSERT, not the components.
- Contradictions found — how many proposed syntheses were
  dropped in Step 5 because an existing user fact contradicts them.
- Flags for janitor — typically equals the Step 0 failures count,
  but can also include: syntheses whose components are all archived,
  entities with single-fact single-day mentions that look like
  transient noise, etc.
- Next run — literal "tomorrow 02:00 local time" is fine; the cron
  schedule does the rest.

## Deferred run variant

If Step 6 hit a WAL lock and the run deferred:

```
[REFLECT] Deferred — WAL lock at Step 6, cached 4 syntheses for retry
Pending: $HERMES_HOME/.hermes/cron/deferred_reflect/state.json
Step 0 failures: 25
Next attempt: ~1h via schedule_1h_retry
```

The state.json will hold a JSON object with key "step": null and
"syntheses": a list of dicts (content, category, components, entities).
The next cron tick (or the explicit retry) will resume from there.
