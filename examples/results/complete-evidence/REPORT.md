# Local functional experiment

This is an engineered scripted-actor demonstration, not evidence of LLM improvement.

| Policy | Runs | Compliant success | Completion | Hard-violation runs | Checks | Rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 80 | 0.300 | 0.350 | 0.150 | 80 | 0 |
| fixed | 80 | 0.850 | 1.000 | 0.150 | 174 | 42 |
| fixed-full | 80 | 0.850 | 1.000 | 0.150 | 174 | 42 |
| dynamic | 80 | 0.850 | 1.000 | 0.150 | 174 | 42 |

Unknown evidence is not a pass. Historical input writes remain violations even after restoration.
Candidate effects occur only in cloned virtual state; a rejected candidate never commits.
Call/action counters alone do not establish compute fairness; local model_usage records tokens separately.
