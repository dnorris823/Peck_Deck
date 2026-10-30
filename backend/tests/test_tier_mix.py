"""The per-feeder tier mix on GET /devices, and when it warns about Tier 2."""
from backend.devices.operations import summarize_tier_mix, tier2_missed


def _attempt(tier, outcome):
    return {"tier": tier, "outcome": outcome, "confidence": None, "threshold": 0.6}


# Traces as the Pi sends them under TIER_PREFERENCE=gpu: Tier 2, then Tier 1.
GPU_ANSWERED = ("gpu", [_attempt("gpu", "accepted"), _attempt("local", "not_run")])
GPU_DOWN = ("local", [_attempt("gpu", "failed"), _attempt("local", "accepted")])
GPU_UNSURE = ("local", [_attempt("gpu", "below_threshold"), _attempt("local", "accepted")])
ALL_FAILED = ("none", [_attempt("gpu", "failed"), _attempt("local", "failed")])
OVERFLOW = ("none", [_attempt("gpu", "not_run"), _attempt("local", "not_run")])


def test_a_failed_tier2_is_a_miss():
    assert tier2_missed(*GPU_DOWN) is True
    assert tier2_missed(*ALL_FAILED) is True


def test_a_tier2_answer_below_its_bar_is_not_a_miss():
    # Tier 1 named it, but the GPU server answered. Counting this would warn
    # about a healthy server on every hard bird.
    assert tier2_missed(*GPU_UNSURE) is False
    assert tier2_missed(*GPU_ANSWERED) is False


def test_a_classify_queue_overflow_is_a_miss():
    assert tier2_missed(*OVERFLOW) is True


def test_a_capture_that_never_asked_tier2_is_left_out():
    # TIER_PREFERENCE=auto: Tier 1 answered first.
    auto = ("local", [_attempt("local", "accepted"), _attempt("gpu", "not_run")])
    assert tier2_missed(*auto) is None
    # TIER_PREFERENCE=local has no Tier 2 in its chain at all.
    assert tier2_missed("none", [_attempt("local", "failed")]) is None


def test_a_capture_without_a_trace_assumes_the_gpu_order():
    assert tier2_missed("local", None) is True
    assert tier2_missed("none", None) is True
    assert tier2_missed("gpu", None) is False


def test_counts_come_from_the_tier_that_answered():
    mix = summarize_tier_mix([GPU_ANSWERED] * 4 + [GPU_UNSURE, ALL_FAILED, ("cloud", None)])
    assert (mix["gpu"], mix["local"], mix["cloud"], mix["none"]) == (4, 1, 1, 1)
    assert mix["window_hours"] == 24


def test_a_quiet_feeder_with_two_visits_does_not_warn():
    mix = summarize_tier_mix([GPU_DOWN, ALL_FAILED])
    assert (mix["tier2_asked"], mix["tier2_missed"]) == (2, 2)
    assert mix["tier2_warning"] is False


def test_three_misses_warn_once_they_reach_a_fifth():
    assert summarize_tier_mix([GPU_DOWN] * 3)["tier2_warning"] is True
    # 3 of 15 is exactly 20%.
    assert summarize_tier_mix([GPU_DOWN] * 3 + [GPU_ANSWERED] * 12)["tier2_warning"] is True
    # 3 of 16 is under it: a busy feeder rides out a few timeouts.
    assert summarize_tier_mix([GPU_DOWN] * 3 + [GPU_ANSWERED] * 13)["tier2_warning"] is False


def test_unsure_tier2_answers_never_warn():
    assert summarize_tier_mix([GPU_UNSURE] * 10)["tier2_warning"] is False


def test_devices_carry_the_tier_mix(client, owner_headers):
    res = client.get("/devices", headers=owner_headers)
    assert res.status_code == 200
    by_name = {d["name"]: d["tier_mix"] for d in res.json()}
    # Dev One's seeded visits are from now, with no trace: 2 gpu and 3 local.
    # Without a trace, local counts as a miss, so 3 of 5 missed Tier 2.
    dev1 = by_name["Dev One"]
    assert (dev1["gpu"], dev1["local"]) == (2, 3)
    assert (dev1["tier2_asked"], dev1["tier2_missed"]) == (5, 3)
    assert dev1["tier2_warning"] is True
    # Dev Two's only visit is 3 days old, outside the 24 h window.
    assert by_name["Dev Two"] == {
        "window_hours": 24, "gpu": 0, "local": 0, "cloud": 0, "none": 0,
        "tier2_asked": 0, "tier2_missed": 0, "tier2_warning": False,
    }
