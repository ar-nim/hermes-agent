# Cross-Skill Coherence Review Pattern

**When triggered:** When one or more skills in a skill family are updated, audit all related skills for cross-contamination of old assumptions.

Skills should be kept structurally aligned. When one skill changes its quoting or contradiction policy, the others must be updated to match — otherwise the agent gets conflicting discipline across skills.

---

## Coherence Criteria (the checklist that surfaces issues)

Apply these five checks to every skill in the family when one skill is updated:

### 1. Category Sharding Alignment
**What to check:** Does every skill that writes to or references categories use the current distribution model?
**What went wrong:** Reflect Step 5 hardcoded `category='general'` for all synthesis. Best-practices had corrected this to "category is load-bearing, distribute accurately."
**Signal:** Search for `category='general'` or `category="general"` in the skill body. If other skills in the family now distribute across categories, the hardcoded default is stale.

### 2. Update vs. Add Decision Gate
**What to check:** Does the skill have a decision tree for when to use `update` vs `add` or `remove+add`?
**What went wrong:** Reflect had no such gate — all synthesis went through `add` even when an insight was a direct evolution of a single source fact.
**Signal:** Search the skill body for `fact_store.*add` without any `update` branches. If the skill writes synthesis and has no update path, it's missing the gate.

### 3. Hygiene Escalation Protocol
**What to check:** Does the skill check category bank size before writing, and does it construct Janitor warnings?
**What went wrong:** Reflect Step 6 ran contradiction checks with no size awareness. When synthesis fills `general` to 400+, the contradiction gate becomes unreliable.
**Signal:** Search for `contradict` in the skill. If contradiction checks exist without a size threshold warning, hygiene escalation is missing.

### 4. Minimal Quoting Alignment
**What to check:** Does the skill's content examples follow the Minimal Quoting Rule?
**What went wrong:** Reflect had no quoting guidance — synthesis content examples quoted everything, including multi-word capitalized phrases.
**Signal:** Search for entity-quoting patterns. If examples show `"Home Network"` or `"Acme OfficeTower"` (quoted), the skill is on the old standard. Current rule: quote only single-word lowercase terms, not capitalized phrases.

### 5. Temporal Decay Defaults
**What to check:** Does the skill mention `temporal_decay_half_life` and its default (0 = disabled)?
**What went wrong:** Reflect had no mention. Best-practices added explicit clarification that decay defaults to disabled.
**Signal:** If a skill mentions decay at all without noting the default is 0, it's incomplete relative to current best-practices.

---

## Additional Checks (secondary signals)

- **Version metadata drift:** If frontmatter has `version` at top level AND in `metadata.hermes.version`, the skill may have been partially synced (other skills now keep version only in `metadata.hermes`).
- **Cron time contradictions:** If a skill's principles say one time and its example tables say another, someone updated half the skill.
- **Stale red-herring language:** if a step warns about a tool as if it's an active hazard but the tool was already fixed, the warning is stale — remove it from the body, not just the changelog.
- **Related skills list drift:** If `related_skills` in frontmatter points to skills that have been renamed or deleted, the skill is stale at the metadata level.

---

## How to Run a Coherence Review

1. **Identify the skill family.** Look at `related_skills` in frontmatter — those are the siblings.
2. **Read the most recently updated skill in the family** to establish the current standard.
3. **Run the 5 coherence checks** against each older skill.
4. **Patch first, report second.** Do not present a list of issues without having the patches ready. The audit and the fix are one session.
5. **Update `metadata.hermes.updated` and append to `changes`** in the patched skill.

---

When skills are updated in a batch, update all of them together — skipping one leaves it structurally behind.
