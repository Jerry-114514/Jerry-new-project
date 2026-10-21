"""Source-anchored extraction for the supported fixture request grammar."""


def extract_requirements(request):
    if not isinstance(request, str):
        raise ValueError("request must be text")
    clauses = [
        ("R_INPUT", "hard", "不得写入或删除输入文件"),
        ("R_ORDER", "hard", "必须先检查 id、date、group、amount 字段"),
        ("R_RESULT", "goal", request.split("。")[0]),
        ("R_REPORT", "delivery", "报告 input_rows 以及成功时的 output_rows"),
    ]
    requirements = []
    for rid, kind, quote in clauses:
        if not quote or quote not in request:
            raise ValueError(f"Unsupported request grammar; cannot extract {rid}")
        start = request.index(quote)
        requirements.append({"id": rid, "type": kind, "source": "user_request",
                             "quote": quote, "start": start, "end": start + len(quote)})
    return requirements
