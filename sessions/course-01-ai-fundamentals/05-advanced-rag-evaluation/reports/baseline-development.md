# RAG baseline — development

Questions and expected results come from `data/evaluations/rag_cases.json`.

## early-first-crewed

- **Question:** Which mission was the first crewed Apollo flight and where did it operate?
- **Expected sources:** 01-early-apollo-missions.md
- **Expected sections:** Apollo 7: the first crewed Apollo flight
- **Expected facts:** Apollo 7, Earth orbit
- **Retrieved sources:** 01-early-apollo-missions.md, 02-first-lunar-landings.md
- **Cited sources:** 01-early-apollo-missions.md
- **Answer:** The first crewed Apollo flight was Apollo 7, which operated in Earth orbit.

| Source recall | Fact coverage | Answerability | Citation validity |
|---:|---:|---:|---:|
| 1.00 | 1.00 | 1 | 1 |

## landing-crew-roles

- **Question:** On Apollo 11, who walked on the Moon and who stayed in lunar orbit?
- **Expected sources:** 02-first-lunar-landings.md
- **Expected sections:** Apollo 11: first humans on the lunar surface
- **Expected facts:** Neil Armstrong, Buzz Aldrin, Michael Collins
- **Retrieved sources:** 02-first-lunar-landings.md, 03-apollo-13-incident.md
- **Cited sources:** 02-first-lunar-landings.md
- **Answer:** On Apollo 11, Neil Armstrong and Buzz Aldrin walked on the Moon, while Michael Collins stayed in lunar orbit.

| Source recall | Fact coverage | Answerability | Citation validity |
|---:|---:|---:|---:|
| 1.00 | 1.00 | 1 | 1 |

## incident-lifeboat

- **Question:** Why was Apollo 13's landing aborted, and how did the crew use the lunar module?
- **Expected sources:** 03-apollo-13-incident.md
- **Expected sections:** Explosion and change of mission
- **Expected facts:** explosion, lifeboat, April 17
- **Retrieved sources:** 03-apollo-13-incident.md, 02-first-lunar-landings.md
- **Cited sources:** 03-apollo-13-incident.md
- **Answer:** Apollo 13's landing was aborted because an explosion damaged the spacecraft, ending the lunar-landing objective. Instead of landing, the crew circled the Moon and used the lunar module as a lifeboat during the emergency to ensure their safe return to Earth.

| Source recall | Fact coverage | Answerability | Citation validity |
|---:|---:|---:|---:|
| 1.00 | 0.67 | 1 | 1 |

## surface-final-mission

- **Question:** What made Apollo 17 notable, and how much lunar material did it collect?
- **Expected sources:** 04-later-surface-exploration.md
- **Expected sections:** Apollo 17: the final Apollo lunar mission
- **Expected facts:** final Apollo lunar mission, Harrison Schmitt, 243 pounds
- **Retrieved sources:** 04-later-surface-exploration.md, 02-first-lunar-landings.md
- **Cited sources:** 04-later-surface-exploration.md
- **Answer:** Apollo 17 was notable for being the final Apollo lunar mission and for having Harrison Schmitt as the first scientist-astronaut to reach the Moon. During the mission, the crew completed three moonwalks and collected 243 pounds of lunar material.

| Source recall | Fact coverage | Answerability | Citation validity |
|---:|---:|---:|---:|
| 1.00 | 1.00 | 1 | 1 |

## absent-apollo-14

- **Question:** Which experiments did Apollo 14 deploy on the lunar surface?
- **Expected sources:** none
- **Expected sections:** none
- **Expected facts:** none
- **Retrieved sources:** 04-later-surface-exploration.md, 02-first-lunar-landings.md
- **Cited sources:** none
- **Answer:** The provided context does not include information about the experiments deployed on the lunar surface by Apollo 14.

| Source recall | Fact coverage | Answerability | Citation validity |
|---:|---:|---:|---:|
| 1.00 | 1.00 | 1 | 1 |
