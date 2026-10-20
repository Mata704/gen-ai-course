# RAG version comparison

**Quality gate: FAIL**

## Average results

| Version | Retrieval | Fact coverage | Answerability | Citation validity | Latency ms | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1.000 | 0.750 | 1.000 | 1.000 | 706.7 | 395.0 |
| candidate | 1.000 | 0.889 | 0.833 | 1.000 | 790.0 | 428.3 |

## Improvements

| Case | Metric | Baseline | Candidate |
|---|---|---:|---:|
| landing-exact-identifier | fact_coverage | 0.000 | 1.000 |
| surface-rover-distance | fact_coverage | 0.500 | 1.000 |

## Why the gate failed

- candidate answerability is below 0.90
- candidate has a critical per-case regression

## Regressions

| Case | Critical? | Metric | Baseline | Candidate |
|---|---|---|---:|---:|
| incident-lifeboat | yes | fact_coverage | 1.000 | 0.667 |
| surface-final-mission | yes | fact_coverage | 1.000 | 0.667 |
| absent-apollo-14 | yes | answerability | 1.000 | 0.000 |

## Case details

Questions and expected results come from `test-data/rag-version-runs.json`.

### landing-exact-identifier

- **Question:** Which mission visited Surveyor 3?
- **Expected sources:** 02-first-lunar-landings.md
- **Expected facts:** Apollo 12, Surveyor 3

**Baseline**

- Retrieved sources: 02-first-lunar-landings.md, 01-early-apollo-missions.md
- Cited sources: 02-first-lunar-landings.md
- Answer: Apollo 11 was the first lunar landing.

**Candidate**

- Retrieved sources: 02-first-lunar-landings.md, 04-later-surface-exploration.md
- Cited sources: 02-first-lunar-landings.md
- Answer: Apollo 12 visited Surveyor 3.

### incident-lifeboat

- **Question:** Why was Apollo 13's landing aborted, and how did the crew use the lunar module?
- **Expected sources:** 03-apollo-13-incident.md
- **Expected facts:** explosion, lifeboat, April 17

**Baseline**

- Retrieved sources: 03-apollo-13-incident.md, 02-first-lunar-landings.md
- Cited sources: 03-apollo-13-incident.md
- Answer: An explosion ended the landing plan. The lunar module became a lifeboat, and the crew returned on April 17.

**Candidate**

- Retrieved sources: 03-apollo-13-incident.md, 01-early-apollo-missions.md
- Cited sources: 03-apollo-13-incident.md
- Answer: An explosion ended the planned landing and the crew used the lunar module as a lifeboat.

### surface-rover-distance

- **Question:** Which mission first used the lunar rover, and how far did it travel?
- **Expected sources:** 04-later-surface-exploration.md
- **Expected facts:** Apollo 15, 17 miles

**Baseline**

- Retrieved sources: 04-later-surface-exploration.md, 02-first-lunar-landings.md
- Cited sources: 04-later-surface-exploration.md
- Answer: Apollo 15 first used the lunar rover.

**Candidate**

- Retrieved sources: 04-later-surface-exploration.md, 03-apollo-13-incident.md
- Cited sources: 04-later-surface-exploration.md
- Answer: Apollo 15 first used the lunar rover and travelled more than 17 miles.

### surface-final-mission

- **Question:** What made Apollo 17 notable, and how much lunar material did it collect?
- **Expected sources:** 04-later-surface-exploration.md
- **Expected facts:** final Apollo lunar mission, Harrison Schmitt, 243 pounds

**Baseline**

- Retrieved sources: 04-later-surface-exploration.md, 02-first-lunar-landings.md
- Cited sources: 04-later-surface-exploration.md
- Answer: Apollo 17 was the final Apollo lunar mission. Harrison Schmitt joined the crew, which collected 243 pounds.

**Candidate**

- Retrieved sources: 04-later-surface-exploration.md, 01-early-apollo-missions.md
- Cited sources: 01-early-apollo-missions.md
- Answer: Apollo 17 was the final Apollo lunar mission and collected 243 pounds.

### absent-apollo-14

- **Question:** Which experiments did Apollo 14 deploy on the lunar surface?
- **Expected sources:** none
- **Expected facts:** none

**Baseline**

- Retrieved sources: 02-first-lunar-landings.md, 04-later-surface-exploration.md
- Cited sources: none
- Answer: The corpus does not contain enough information about Apollo 14 experiments.

**Candidate**

- Retrieved sources: 02-first-lunar-landings.md, 04-later-surface-exploration.md
- Cited sources: 02-first-lunar-landings.md
- Answer: Apollo 14 deployed experiments on the lunar surface.

### absent-mars

- **Question:** Which Apollo mission landed on Mars?
- **Expected sources:** none
- **Expected facts:** none

**Baseline**

- Retrieved sources: 01-early-apollo-missions.md, 02-first-lunar-landings.md
- Cited sources: none
- Answer: No Apollo mission in this corpus landed on Mars.

**Candidate**

- Retrieved sources: 01-early-apollo-missions.md, 03-apollo-13-incident.md
- Cited sources: none
- Answer: The corpus does not support a Mars landing.

Citation validity only checks whether the cited file was retrieved. It does not prove that the file supports the claim.

## Questions

1. Would you release the candidate? Show one improvement and one serious problem.
2. Does a good metric hide an error in any case? Which one?
