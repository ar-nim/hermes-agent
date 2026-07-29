# Hindsight Architecture (Reference)

Source: arxiv.org/abs/2512.12818, github.com/vectorize-io/hindsight

## Core Architecture: Four Logical Memory Networks

Hindsight implements a structured memory with four distinct layers:

1. **World Facts** — objective facts about the environment
2. **Agent Experiences** — episodic traces of what the agent did
3. **Entity Summaries** — synthesized higher-order understanding of key entities
4. **Evolving Beliefs** — how the agent's beliefs change over time

## Three Core Operations

| Operation | Description |
|---|---|
| **Retain** | Store new information in the appropriate network |
| **Recall** | Retrieve relevant facts from memory |
| **Reflect** | Reason over the memory bank and update it — the key generative action |

## Why Reflect Is the Key Differentiator

`Reflect` in Hindsight is not a retrieval operation — it's synthesis. It reads across the memory networks, identifies patterns, and writes back a higher-order representation. This is exactly what holographic-memory-reflect aims to do.

## Benchmark Performance

- **LongMemEval**: 91.4% accuracy
- **LoCoMo**: 89.61% F1
- **Multi-hop retrieval**: ~85%+ (vs mem9's 22.6% on LoCoMo multi-hop)

## Integration

Hindsight offers integrations with:
- Hermes Agent
- Claude Code
- OpenClaw

## Key Insight for Reflect Skill Design

Hindsight's `reflect` operation is traceable — it produces a verifiable output that can be audited. This is important: autonomous synthesis without audit trails is dangerous. The holographic reflect skill should produce summary facts that cite the source fact IDs.
