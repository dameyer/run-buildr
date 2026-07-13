from app.services.plan import _adjust_repeats_for_wahoo


def test_non_repeat_intervals_unchanged():
    intervals = [
        {"exit_trigger_type": "time", "exit_trigger_value": 300},
        {"exit_trigger_type": "distance", "exit_trigger_value": 400},
    ]
    result = _adjust_repeats_for_wahoo(intervals)
    assert result[0]["exit_trigger_value"] == 300
    assert result[1]["exit_trigger_value"] == 400


def test_repeat_decremented_by_one():
    intervals = [{"exit_trigger_type": "repeat", "exit_trigger_value": 4, "intervals": []}]
    result = _adjust_repeats_for_wahoo(intervals)
    assert result[0]["exit_trigger_value"] == 3


def test_repeat_minimum_zero():
    intervals = [{"exit_trigger_type": "repeat", "exit_trigger_value": 1, "intervals": []}]
    result = _adjust_repeats_for_wahoo(intervals)
    assert result[0]["exit_trigger_value"] == 0


def test_repeat_already_zero_stays_zero():
    intervals = [{"exit_trigger_type": "repeat", "exit_trigger_value": 0, "intervals": []}]
    result = _adjust_repeats_for_wahoo(intervals)
    assert result[0]["exit_trigger_value"] == 0


def test_nested_repeats_decremented():
    intervals = [
        {
            "exit_trigger_type": "repeat",
            "exit_trigger_value": 3,
            "intervals": [
                {"exit_trigger_type": "repeat", "exit_trigger_value": 2, "intervals": []}
            ],
        }
    ]
    result = _adjust_repeats_for_wahoo(intervals)
    assert result[0]["exit_trigger_value"] == 2
    assert result[0]["intervals"][0]["exit_trigger_value"] == 1


def test_does_not_mutate_input():
    original = {"exit_trigger_type": "repeat", "exit_trigger_value": 4, "intervals": []}
    _adjust_repeats_for_wahoo([original])
    assert original["exit_trigger_value"] == 4
