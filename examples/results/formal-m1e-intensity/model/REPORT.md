# Local functional experiment

Real local causal-LM inference. Inspect JSON errors, token usage and dataset limitations; a smoke run is not efficacy evidence.

| Policy | Runs | Compliant success | Completion | Hard-violation runs | Checks | Rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-k | 8 | 0.250 | 0.250 | 0.000 | 8 | 0 |
| dynamic-k | 8 | 0.250 | 0.250 | 0.000 | 8 | 0 |

Unknown evidence is not a pass. Historical input writes remain violations even after restoration.
Candidate effects occur only in cloned virtual state; a rejected candidate never commits.
Call/action counters alone do not establish compute fairness; local model_usage records tokens separately.
