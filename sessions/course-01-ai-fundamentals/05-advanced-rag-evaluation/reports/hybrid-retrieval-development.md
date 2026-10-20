# Hybrid retrieval comparison — development

All methods use the same final top_k: **2**.
Questions and expected sources come from `data/evaluations/rag_cases.json`.
Session-specific distractor chunks make ranking errors visible without changing earlier sessions.
This exercise evaluates retrieval only: it does not generate answers or citations.

## early-first-crewed

Which mission was the first crewed Apollo flight and where did it operate?

Expected source: 01-early-apollo-missions.md
Expected section: Apollo 7: the first crewed Apollo flight

Generated answer: **N/A — retrieval-only exercise**

Cited sources: **N/A — retrieval-only exercise**

| Method | Rank | Source | Section | Preview | Relevant section? |
|---|---:|---|---|---|---|
| semantic | 1 | 01-early-apollo-missions.md | Apollo 8: the first crewed lunar orbit | Document: Early Apollo missions Section: Apollo 8: the first crewed lunar orbit Apollo 8 l | no |
| semantic | 2 | 01-early-apollo-missions.md | Apollo 7: the first crewed Apollo flight | Document: Early Apollo missions Section: Apollo 7: the first crewed Apollo flight Apollo 7 | yes |
| lexical | 1 | 01-early-apollo-missions.md | Apollo 7: the first crewed Apollo flight | Document: Early Apollo missions Section: Apollo 7: the first crewed Apollo flight Apollo 7 | yes |
| lexical | 2 | 01-early-apollo-missions.md | Apollo 8: the first crewed lunar orbit | Document: Early Apollo missions Section: Apollo 8: the first crewed lunar orbit Apollo 8 l | no |
| hybrid | 1 | 01-early-apollo-missions.md | Apollo 8: the first crewed lunar orbit | Document: Early Apollo missions Section: Apollo 8: the first crewed lunar orbit Apollo 8 l | no |
| hybrid | 2 | 01-early-apollo-missions.md | Apollo 7: the first crewed Apollo flight | Document: Early Apollo missions Section: Apollo 7: the first crewed Apollo flight Apollo 7 | yes |

## landing-crew-roles

On Apollo 11, who walked on the Moon and who stayed in lunar orbit?

Expected source: 02-first-lunar-landings.md
Expected section: Apollo 11: first humans on the lunar surface

Generated answer: **N/A — retrieval-only exercise**

Cited sources: **N/A — retrieval-only exercise**

| Method | Rank | Source | Section | Preview | Relevant section? |
|---|---:|---|---|---|---|
| semantic | 1 | 02-first-lunar-landings.md | Apollo 11: first humans on the lunar surface | Document: The first Apollo lunar landings Section: Apollo 11: first humans on the lunar su | yes |
| semantic | 2 | 03-apollo-13-incident.md | Safe return | Document: Apollo 13: an aborted landing Section: Safe return Apollo 13 splashed down safel | no |
| lexical | 1 | 02-first-lunar-landings.md | Apollo 11: first humans on the lunar surface | Document: The first Apollo lunar landings Section: Apollo 11: first humans on the lunar su | yes |
| lexical | 2 | 05-retrieval-distractors.md | Landing, orbit and lunar module glossary | Document: Retrieval distractors Section: Landing, orbit and lunar module glossary A crew c | no |
| hybrid | 1 | 02-first-lunar-landings.md | Apollo 11: first humans on the lunar surface | Document: The first Apollo lunar landings Section: Apollo 11: first humans on the lunar su | yes |
| hybrid | 2 | 05-retrieval-distractors.md | Landing, orbit and lunar module glossary | Document: Retrieval distractors Section: Landing, orbit and lunar module glossary A crew c | no |

## incident-lifeboat

Why was Apollo 13's landing aborted, and how did the crew use the lunar module?

Expected source: 03-apollo-13-incident.md
Expected section: Explosion and change of mission

Generated answer: **N/A — retrieval-only exercise**

Cited sources: **N/A — retrieval-only exercise**

| Method | Rank | Source | Section | Preview | Relevant section? |
|---|---:|---|---|---|---|
| semantic | 1 | 03-apollo-13-incident.md | Explosion and change of mission | Document: Apollo 13: an aborted landing Section: Explosion and change of mission An explos | yes |
| semantic | 2 | 03-apollo-13-incident.md | Planned destination and launch | Document: Apollo 13: an aborted landing Section: Planned destination and launch Apollo 13  | no |
| lexical | 1 | 03-apollo-13-incident.md | Planned destination and launch | Document: Apollo 13: an aborted landing Section: Planned destination and launch Apollo 13  | no |
| lexical | 2 | 03-apollo-13-incident.md | Explosion and change of mission | Document: Apollo 13: an aborted landing Section: Explosion and change of mission An explos | yes |
| hybrid | 1 | 03-apollo-13-incident.md | Explosion and change of mission | Document: Apollo 13: an aborted landing Section: Explosion and change of mission An explos | yes |
| hybrid | 2 | 03-apollo-13-incident.md | Planned destination and launch | Document: Apollo 13: an aborted landing Section: Planned destination and launch Apollo 13  | no |

## surface-final-mission

What made Apollo 17 notable, and how much lunar material did it collect?

Expected source: 04-later-surface-exploration.md
Expected section: Apollo 17: the final Apollo lunar mission

Generated answer: **N/A — retrieval-only exercise**

Cited sources: **N/A — retrieval-only exercise**

| Method | Rank | Source | Section | Preview | Relevant section? |
|---|---:|---|---|---|---|
| semantic | 1 | 04-later-surface-exploration.md | Apollo 17: the final Apollo lunar mission | Document: Later Apollo surface exploration Section: Apollo 17: the final Apollo lunar miss | yes |
| semantic | 2 | 05-retrieval-distractors.md | Surface exploration measurements | Document: Retrieval distractors Section: Surface exploration measurements Later missions u | no |
| lexical | 1 | 04-later-surface-exploration.md | Apollo 17: the final Apollo lunar mission | Document: Later Apollo surface exploration Section: Apollo 17: the final Apollo lunar miss | yes |
| lexical | 2 | 01-early-apollo-missions.md | Apollo 8: the first crewed lunar orbit | Document: Early Apollo missions Section: Apollo 8: the first crewed lunar orbit Apollo 8 l | no |
| hybrid | 1 | 04-later-surface-exploration.md | Apollo 17: the final Apollo lunar mission | Document: Later Apollo surface exploration Section: Apollo 17: the final Apollo lunar miss | yes |
| hybrid | 2 | 01-early-apollo-missions.md | Apollo 8: the first crewed lunar orbit | Document: Early Apollo missions Section: Apollo 8: the first crewed lunar orbit Apollo 8 l | no |

## absent-apollo-14

Which experiments did Apollo 14 deploy on the lunar surface?

Expected source: none (test abstention)
Expected section: none

Generated answer: **N/A — retrieval-only exercise**

Cited sources: **N/A — retrieval-only exercise**

| Method | Rank | Source | Section | Preview | Relevant section? |
|---|---:|---|---|---|---|
| semantic | 1 | 04-later-surface-exploration.md | Apollo 15: the first Lunar Roving Vehicle | Document: Later Apollo surface exploration Section: Apollo 15: the first Lunar Roving Vehi | n/a |
| semantic | 2 | 02-first-lunar-landings.md | Apollo 12: a precision destination | Document: The first Apollo lunar landings Section: Apollo 12: a precision destination Apol | n/a |
| lexical | 1 | 02-first-lunar-landings.md | Apollo 11: first humans on the lunar surface | Document: The first Apollo lunar landings Section: Apollo 11: first humans on the lunar su | n/a |
| lexical | 2 | 02-first-lunar-landings.md | Apollo 12: a precision destination | Document: The first Apollo lunar landings Section: Apollo 12: a precision destination Apol | n/a |
| hybrid | 1 | 02-first-lunar-landings.md | Apollo 12: a precision destination | Document: The first Apollo lunar landings Section: Apollo 12: a precision destination Apol | n/a |
| hybrid | 2 | 04-later-surface-exploration.md | Apollo 15: the first Lunar Roving Vehicle | Document: Later Apollo surface exploration Section: Apollo 15: the first Lunar Roving Vehi | n/a |

## Answerable cases: ranking quality

| Method | Correct section at rank 1 | Section recall@k | Mean first relevant rank¹ |
|---|---:|---:|---:|
| semantic | **0.750** | **1.000** | **1.25** |
| lexical | **0.750** | **1.000** | **1.25** |
| hybrid | **0.750** | **1.000** | **1.25** |

**Best overall on this split:** semantic, lexical, hybrid.

Bold values are the best result for each metric. A lower mean rank is better.
¹ A miss is counted as rank 3.

## Questions

1. Which method found the most useful chunks? Show one example.
2. Would you use semantic, lexical or hybrid retrieval? Why?
