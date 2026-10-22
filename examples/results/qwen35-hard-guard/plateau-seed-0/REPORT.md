# Local functional experiment

Real local causal-LM inference. Inspect JSON errors, token usage and dataset limitations; a smoke run is not efficacy evidence.

| Policy | Runs | Compliant success | Completion | Hard-violation runs | Checks | Rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-full | 2 | 1.000 | 1.000 | 0.000 | 5 | 1 |
| dynamic | 2 | 1.000 | 1.000 | 0.000 | 5 | 1 |

Unknown evidence is not a pass. Historical input writes remain violations even after restoration.
Candidate effects occur only in cloned virtual state; a rejected candidate never commits.
Call/action counters alone do not establish compute fairness; local model_usage records tokens separately.
