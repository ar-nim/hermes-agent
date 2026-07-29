# Wiki-First Audit Pattern


**Source:** 4-way reranking session — User had to correct twice before wiki was checked

## The Lesson

When running structured audits (reranking, trust reweighting, contradiction scanning), **if the llm-wiki skill is installed, check it before assigning signals** — the wiki is often more current than fact_store on fast-moving life events. If no wiki is configured, skip this step.

## Mandatory Pre-Audit Sequence

1. `fact_store(action='list')` — get current fact inventory
2. **If a wiki exists** (resolve via the `WIKI_PATH` env var — e.g. `${WIKI_PATH:-$HOME/wiki}` — or profile wikis from llm-wiki), use `search_files` to check for more current information on the same topics. Skip if no wiki is configured.
3. `session_search` — check session history for user-confirmed updates
4. `skill_view` — load relevant skills for ground-truth schedules/endpoints
5. Only then: assign signals and build dry-run table

## Why This Matters

During a routine audit, fact 906 (EmployerE EmploymentTransition rumour) was still tagged `this-week` and rated at trust 0.60. The wiki already had full EmploymentTransition documentation with confirmed details:
- Last day: [transition end date]
- Severance: [amount, gross/net]
- Termination agreement signed
- Exit documents wiki pages at P0/P1/P2 priority

The audit would have caught this immediately if the wiki was checked first.

## Cross-Profile Wiki Priority

- If a couple/shared-profile wiki is configured, life-event/relationship facts → PartnerWiki (`shared-profile`) is usually more current
- If the default wiki is configured, health/finance/work facts → default wiki is usually more current
- Always check both when the topic crosses profiles

## For Structured Reranking Prompts

The user may provide a reranking prompt with 4 sources in authority order:
1. Session history (what User explicitly said/confirmed)
2. Skills (ground-truth schedules, endpoints, cron IDs)
3. LLM Wiki (compiled knowledge)
4. Fact_store (self-consistency)

In this framework, when a wiki IS configured it ranks ABOVE fact_store — but only if present. Always follow the user's authority ordering when provided.

## Insurance Fact Handling

**Pitfall:** During contradiction scanning, fact 374 ("User has no life insurance yet") was flagged as contradicted by fact 375 (InsurerC ProductS policy). I was about to demote it. User corrected: "My InsurerC is not life insurance, it's a sakit kritis plan I believe. I forgot if it has life insurance or not. Better not to touch it."

**Rule:** When auditing policy/health facts:
- Don't assume policy type from fact_store content alone
- The user's own understanding of their policy supersedes fact_store claims
- Bundled policies (InsurerC ProductS) can have multiple components — a fact about one component doesn't necessarily contradict a fact about another
- When in doubt about policy/health facts → HOLD, don't demote
- Ask the user before making changes to policy, health, or financial facts
