import os
#!/usr/bin/env python3
"""
reflect_gap_analysis.py — entity-pair co-occurrence for synthesis coverage gaps.

Finds entity pairs with 5+ shared reliable facts that are NOT yet covered
by any existing synthesis. Ranks by shared-fact count to surface the most
promising synthesis themes.

Usage:
    python3 reflect_gap_analysis.py

Output: top 25 uncovered entity pairs, plus entity mention distribution stats.
"""
import sqlite3, os, re

db = os.environ.get('HERMES_HOME', os.path.join(os.path.expanduser(os.environ.get('HERMES_HOME', '~/.hermes')), '.hermes', 'memory_store.db')) + '/memory_store.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# ---- Load existing syntheses for covered-pair tracking ----
cur.execute("SELECT fact_id, content FROM facts WHERE tags LIKE '%type:synthesis%'")
synth_texts = {r[0]: r[1] for r in cur.fetchall()}

# ---- Load reliable facts ----
cur.execute(
    "SELECT fact_id, content FROM facts "
    "WHERE trust_score >= 0.5 AND (tags IS NULL OR tags NOT LIKE '%status:archived%')"
)
facts = cur.fetchall()

# ---- Entity extraction ----
quoted_re = re.compile(r'"([^"]+)"')
titlecase_re = re.compile(r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*)\b')
STOPWORDS = {
    'The','A','User','Source','Open','Meteo','May','This','When','Key',
    'It','He','She','They','We','I','An','In','Is','Are','Was','Were',
    'Be','Been','Being','Have','Has','Had','Do','Does','Did','Will',
    'Would','Could','Should','May','Might','Must','Shall','Can','To',
    'Of','In','For','On','With','At','By','From','As','Into','Through',
    'During','Before','After','Above','Below','Between','Under','Over',
    'And','Or','But','If','Because','So','Although','Yet','Nor','Too',
    'Very','Just','Only','Even','Still','Also','Then','Than','That',
    'This','These','Those','What','Which','Who','Whom','Whose','Where',
    'When','Why','How','All','Each','Every','Both','Few','More','Most',
    'Other','Some','Such','No','Not','Only','Same','So','Than','Too',
    'Very','One','Two','Three','Four','Five','Six','Seven','Eight',
    'Nine','Ten',
}

entity_facts = {}
for fid, content in facts:
    ents = [e for e in set(quoted_re.findall(content) + titlecase_re.findall(content))
            if e not in STOPWORDS]
    for e in ents:
        entity_facts.setdefault(e, []).append(fid)

# ---- Build covered pair set ----
covered = set()
for fid, txt in synth_texts.items():
    ents = [e for e in set(quoted_re.findall(txt) + titlecase_re.findall(txt))
            if e not in STOPWORDS]
    for i, a in enumerate(ents):
        for b in ents[i+1:]:
            covered.add(tuple(sorted([a, b])))

# ---- Score all pairs ----
pair_scores = []
all_ents = list(entity_facts.keys())
for i, a in enumerate(all_ents):
    for b in all_ents[i+1:]:
        shared = set(entity_facts[a]) & set(entity_facts[b])
        if len(shared) >= 5 and tuple(sorted([a, b])) not in covered:
            pair_scores.append((a, b, len(shared)))

pair_scores.sort(key=lambda x: -x[2])

print("TOP coverage-gap entity pairs (5+ shared facts, not synthesized):")
for a, b, score in pair_scores[:25]:
    print(f"  {a} + {b}: {score} shared facts")

# ---- Entity stats ----
counts = sorted([len(v) for v in entity_facts.values()], reverse=True)
print(f"\nEntity mention distribution:")
print(f"  Total entities: {len(entity_facts)}")
print(f"  Entities with 5+ mentions: {sum(1 for c in counts if c >= 5)}")
print(f"  Entities with 10+ mentions: {sum(1 for c in counts if c >= 10)}")
print(f"  Max: {counts[0]}, Median: {counts[len(counts)//2]}, 90th pct: {counts[int(len(counts)*0.9)]}")

conn.close()