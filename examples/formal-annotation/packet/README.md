# Independent annotation packet

These are unreviewed development candidates, not a released benchmark.
Give cases.jsonl and a separate copy of review-template.jsonl to each reviewer.
Reviewers must not see each other's labels before submitting. Fill reviewer with a stable identity,
set human_verified=true only after actual human review, and judge every listed requirement.
Allowed status: satisfied / violated / unknown. Cite request, input:<path>, file:<path>, or visible event:<index>.
A changed snapshot can prove violation without history; a restored snapshot cannot prove no historical writes.
Known judgments need supporting evidence. Do not infer missing history.
Combine the two completed review files, then run the conflicts command. A different person arbitrates conflicts.
Do not invent reviewer identities or submit automated labels as human verification.
