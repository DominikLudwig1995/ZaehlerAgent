from datetime import timedelta

from app.plausibility import Reading, decide, vote


def test_vote_majority_and_unknown():
    assert vote(["3592352", "3592352", "3592357"]) == ("3592352", 1.0)
    digits, agreement = vote(["35?2352", "3592352"])
    assert digits == "3592352" and agreement == 6 / 7  # one wheel only has a single vote
    assert vote(["3", "4"])[0] == "?"  # a tie is not guessed
    assert vote(["?", "?"])[0] == "?"


def test_first_reading_needs_all_wheels(gas, now):
    assert decide(gas, "3592352", None, now).status == "accepted"
    assert decide(gas, "35?2352", None, now).status == "rejected"


def test_rate_and_rollback(gas, now):
    last = Reading(3592.352, now - timedelta(minutes=10))
    assert decide(gas, "3592360", last, now).value == 3592.36
    assert decide(gas, "3592352", last, now).status == "unchanged"
    # small step back = a half-turned fast wheel, not a real rollback
    assert decide(gas, "3592349", last, now).status == "unchanged"
    big = decide(gas, "3601000", last, now)
    assert big.status == "rejected" and big.value == 3592.352
    back = decide(gas, "1508633", last, now)  # the camera's own misread of 2026-11-21
    assert back.status == "rejected" and "below" in back.reason


def test_unknown_wheels_are_completed_from_the_last_value(gas, now):
    last = Reading(3592.352, now - timedelta(minutes=10))
    d = decide(gas, "35923??", last, now)
    assert d.status == "unchanged" and d.value == 3592.352  # smallest fit is the last value itself
    d = decide(gas, "359?36?", last, now)
    assert d.status == "accepted" and d.value == 3592.36
    assert decide(gas, "9??????", last, now).status == "rejected"
    assert decide(gas, "??????", last, now).status == "rejected"  # wrong length


def test_window_grows_with_the_time_since_the_last_value(gas, now):
    last = Reading(3592.0, now - timedelta(hours=10))
    assert decide(gas, "3600000", last, now).status == "accepted"  # 8 m3 in 10 h is fine at 4 m3/h
