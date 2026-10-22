"""Small explicit dependency graph for selecting repair and recheck scopes."""


DEPENDENCIES = {"R_RESULT": {"R_REPORT"}, "R_REPORT": set(), "R_INPUT": set(), "R_ORDER": set()}


def dependency_closure(targets):
    selected = set(targets)
    pending = list(targets)
    while pending:
        for requirement in DEPENDENCIES.get(pending.pop(), ()):
            if requirement not in selected:
                selected.add(requirement)
                pending.append(requirement)
    return sorted(selected)


def repair_scope(target, policy, rejected_before=False):
    if policy == "fixed-full":
        return ["R_RESULT", "R_REPORT"]
    if policy == "dynamic" and rejected_before:
        expanded = dependency_closure([target])
        return expanded if len(expanded) > 1 else target
    return target
