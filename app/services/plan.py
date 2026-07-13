import base64
import json
from app.schemas import Plan


def _adjust_repeats_for_wahoo(intervals: list) -> list:
    """Wahoo repeat exit_trigger_value is 0-indexed: 0 = 1 repeat. Decrement by 1."""
    result = []
    for iv in intervals:
        iv = dict(iv)
        if iv.get("exit_trigger_type") == "repeat":
            iv["exit_trigger_value"] = max(0, iv["exit_trigger_value"] - 1)
            if iv.get("intervals"):
                iv["intervals"] = _adjust_repeats_for_wahoo(iv["intervals"])
        result.append(iv)
    return result


def plan_to_base64(plan: Plan) -> str:
    data = json.loads(plan.model_dump_json(exclude_none=True))
    data["intervals"] = _adjust_repeats_for_wahoo(data["intervals"])
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return f"data:application/json;base64,{encoded}"
