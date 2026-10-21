# Local functional experiment

This is an engineered scripted-actor demonstration, not evidence of LLM improvement.

| Policy | Runs | Compliant success | Completion | Hard-violation runs | Checks | Rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dynamic | 4 | 0.750 | 1.000 | 0.250 | 10 | 4 |

Unknown evidence is not a pass. Historical input writes remain violations even after restoration.
Candidate effects occur only in cloned virtual state; a rejected candidate never commits.
Call/action counters alone do not establish compute fairness; local model_usage records tokens separately.
