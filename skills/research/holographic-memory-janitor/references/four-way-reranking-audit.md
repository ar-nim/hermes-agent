# 4-Way Reranking Audit Workflow

> Methodology validated on a 20-fact batch.

## Purpose

Systematic fact verification against 4 sources, producing a dry-run table for user approval before any mutations.

## Sources (authority order)

1. **Session history** — what the user explicitly said/confirmed (session_search)
2. **Skills** — ground-truth schedules, endpoints, cron IDs, protocols (skill_view)
3. **Optional external wiki (llm-wiki)** — if installed, compiled knowledge from default + profile wikis; skip if no wiki configured
4. **Fact_store** — self-consistency via contradict() and reason()

## Method

For each candidate fact:
- Query ALL FOUR sources for agreement/contradiction
- Assign signal: ✅ corroborated | ⚠️ mixed/silent/sensitive | 🔴 contradicted | 💀 obsolete

### Signal actions

| Signal | Action |
|--------|--------|
| ✅ | fact_feedback(action='helpful') — promote trust |
| 🔴 | fact_feedback(action='unhelpful') — demote; if content is wrong, flag for update |
| 💀 | fact_store(action='remove') — hard delete (user-approved only) |
| 🔄 | fact_store(action='update') with Trajectory Format |
| ⚠️ | NO CHANGE — hold, especially sensitive-health claims |

### Candidate tiers

- **A. High trust (≥0.55):** verify they're still correct
- **B. Synthesis facts (<0.40):** promote cross-domain gems to 0.35–0.40
- **C. Low trust (0.20–0.35):** zombie facts to re-verify or hard-delete

## Hard rules

- Dry-run table FIRST. Never execute without user approval.
- Sensitive-health (MedicationB, ConditionA, dosing): HOLD. Requires explicit confirmation.
- Synthesis ceiling: 0.45 max. Never outrank component facts.
- fact_feedback only moves trust. Wrong content needs fact_store update.
- Stale ≠ wrong. Check before demoting.
- Cross-profile: PartnerWiki often more current on life-event/relationship facts.
- Batch size: 10–20 facts/session max.

## Dry-run table format

```
| fact_id | Content (80 chars) | Trust | Evidence | Proposed | Rationale |
```

## Report format

```
[RERANK] Audit — YYYY-MM-DD
Audited: N | Boosted: N | Demoted: N | Updated: N | Removed: N | Held: N
Cross-source drift: N (followup needed; wiki-sync only if wiki configured)
```

## Pitfalls discovered

### contradict() only catches entity-overlap, not content contradictions

The contradict() tool returns pairs with high entity overlap and some content similarity. It does NOT catch cases like:
- Fact A: "User has no life insurance" vs Fact B: "InsurerC ProductS policy #POLICY_NUMBER"
These share few entities but directly contradict. **Manual cross-check is required for content-level contradictions.**

### User may hold entire domains from audit

When the user says "better not to touch it" for a domain (e.g., insurance), respect the hold across ALL facts in that domain — don't update some and hold others. The hold is domain-wide.

### Wiki is canonical for employment details

When auditing work/career facts, if a wiki is configured, check its entity pages (e.g. `entities/tokopedia.md`, `concepts/key-output-work-experience.md`) as an additional authoritative source. The wiki often has more detail than fact_store.

### Post-life-event fact lifecycle

After major life events (EmploymentTransition, marriage, relocation):
1. Identity facts need status updates ("JobTitle" → "Former JobTitle")
2. Operational facts (daily schedule, commute) become stale but may still be relevant for a transition period
3. Career facts should be CONSOLIDATED, not nuked — they feed job seeking
4. Financial facts referencing compensation need verification against actuals (severance, new compensation)

### Batch execution model

1. Build dry-run table for 10-20 facts
2. Present to user with clear proposed actions
3. User approves/rejects/adjusts
4. Execute approved actions (demotions + tag fixes first, content updates with confirmation)
5. Boost verified facts
6. Report totals

Do NOT execute and present together — the dry-run table is the approval gate.
