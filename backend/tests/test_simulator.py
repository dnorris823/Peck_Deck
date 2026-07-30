"""Device simulator — visit modelling and image bank (FLEDGE Phase 5).

The simulator's HTTP layer is not re-tested here: it drives the Pi's own
``BackendClient``, and that seam is covered end-to-end against a live server in
``integration_tests/test_contract_simulator.py``. What *is* worth pinning is the
modelling that decides whether the generated feed looks like a bird feeder or
like noise — a uniform species draw or an even hour-of-day spread would produce
a dashboard that is obviously synthetic.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.demo_images import plate_for, render_plate
from backend.simulator import (
    TIER_PROFILE,
    _MAX_CONSECUTIVE_FAILURES,
    backfill_timestamps,
    hour_weight,
    load_species,
    pick_tier,
    run_live,
    species_weights,
)


# ── Species catalogue ────────────────────────────────────────────────────────
def test_species_come_from_the_model_taxonomy():
    """Every simulated species must be one Tier 1 could actually predict."""
    species = load_species()
    assert len(species) >= 12
    names = {s.common_name for s in species}
    assert "Northern Cardinal" in names
    assert "Blue Jay" in names


def test_species_entries_carry_a_binomial_and_a_palette():
    for entry in load_species():
        genus, _, epithet = entry.scientific_name.partition(" ")
        assert genus and epithet, entry
        assert len(entry.palette) == 3


def test_species_weights_have_a_long_tail():
    """A few regulars should dominate — a flat draw reads as fake."""
    w = species_weights(20)
    assert w[0] > w[1] > w[-1]
    assert w[0] / w[-1] >= 10


# ── Visit timing ─────────────────────────────────────────────────────────────
def test_dawn_outweighs_night():
    assert hour_weight(7) > hour_weight(12) > hour_weight(2)
    assert hour_weight(3) < 0.1


def test_backfill_stays_inside_the_window_and_never_lands_in_the_future():
    rng = random.Random(7)
    now = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)
    stamps = backfill_timestamps(rng, 200, 5, now=now)

    assert len(stamps) == 200
    assert stamps == sorted(stamps)
    assert all(s <= now for s in stamps)
    assert all(s >= now - timedelta(days=5) for s in stamps)


def test_backfill_is_day_weighted():
    """Overnight hours (22:00–04:00) should be a small slice of the total."""
    rng = random.Random(11)
    now = datetime(2026, 7, 20, 23, 59, tzinfo=timezone.utc)
    stamps = backfill_timestamps(rng, 400, 10, now=now)

    night = [s for s in stamps if s.hour >= 22 or s.hour <= 4]
    assert len(night) / len(stamps) < 0.15


def test_backfill_is_reproducible_from_a_seed():
    assert backfill_timestamps(random.Random(3), 30, 7) == \
        backfill_timestamps(random.Random(3), 30, 7)


def test_backfill_terminates_when_almost_every_draw_is_in_the_future():
    """Just after midnight, most hours drawn for "today" haven't happened yet.

    The generator retries a bounded number of times rather than looping until
    it has `count` stamps, so this must return (possibly short) rather than hang.
    """
    rng = random.Random(5)
    now = datetime(2026, 7, 20, 0, 3, tzinfo=timezone.utc)
    stamps = backfill_timestamps(rng, 50, 1, now=now)

    assert all(s <= now for s in stamps)


# ── Tier + confidence ────────────────────────────────────────────────────────
def test_confidence_is_plausible_for_the_tier_that_produced_it():
    rng = random.Random(2)
    for _ in range(500):
        tier, confidence = pick_tier(rng)
        low, high = TIER_PROFILE[tier][1]
        assert low <= confidence <= high
        assert 0.0 <= confidence <= 1.0


def test_all_three_tiers_appear_with_gpu_most_common():
    rng = random.Random(4)
    seen = [pick_tier(rng)[0] for _ in range(1000)]
    assert set(seen) == {"local", "gpu", "cloud"}
    assert seen.count("gpu") > seen.count("cloud")


def test_the_cloud_tier_is_the_rare_last_resort():
    """Tier 3 costs an API call per image — it must not dominate the feed."""
    rng = random.Random(6)
    seen = [pick_tier(rng)[0] for _ in range(1000)]
    assert seen.count("cloud") / len(seen) < 0.2


# ── Placeholder images ───────────────────────────────────────────────────────
def test_plate_is_a_real_jpeg_of_a_believable_size():
    data = render_plate(["#b8412c", "#5a1810", "#e5b89c"])
    assert data[:2] == b"\xff\xd8"        # JPEG SOI
    assert data[-2:] == b"\xff\xd9"       # EOI
    # A flat image would compress to a few hundred bytes and be a poor stand-in
    # for the Pi's ~300 KB frames; the cap keeps a live run from bloating the DB.
    assert 5_000 < len(data) < 200_000


def test_plates_differ_by_palette():
    a = render_plate(["#b8412c", "#5a1810", "#e5b89c"])
    b = render_plate(["#3f6e89", "#15263a", "#d4cdb8"])
    assert a != b


def test_plate_generation_is_deterministic_and_cached():
    palette = ["#2d4a36", "#1d3225", "#d4cdb8"]
    assert render_plate(palette, seed=1) == render_plate(palette, seed=1)
    assert plate_for(palette) is plate_for(palette)


def test_short_palettes_are_tolerated():
    """A species created ad-hoc by the Pi may carry no palette at all."""
    assert render_plate(["#7a8a8c"])[:2] == b"\xff\xd8"
    assert render_plate([])[:2] == b"\xff\xd8"


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_cli_defaults_to_a_live_drip():
    from backend.simulator import build_parser

    args = build_parser().parse_args([])
    assert args.mode == "live"
    assert args.limit is None  # runs until interrupted


def test_cli_accepts_repeated_device_tokens():
    from backend.simulator import build_parser

    args = build_parser().parse_args(
        ["--mode", "burst", "--count", "5", "--device-token", "a", "--device-token", "b"]
    )
    assert args.mode == "burst"
    assert args.device_token == ["a", "b"]


def test_cli_rejects_an_unknown_mode():
    from backend.simulator import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--mode", "chaos"])


# ── Live mode's failure bound ────────────────────────────────────────────────
# `run_live` counts *successes*, so the consecutive-failure bound is the only
# thing stopping it spinning forever against a backend that has gone away. It
# referenced `_MAX_CONSECUTIVE_FAILURES` without the constant ever being
# defined, so the give-up path raised NameError instead of giving up — which is
# how a live run actually ended when the API container restarted under it.
def test_the_failure_bound_exists_and_is_sane():
    assert isinstance(_MAX_CONSECUTIVE_FAILURES, int)
    # Enough to ride out an API restart, few enough to notice a dead backend.
    assert 2 <= _MAX_CONSECUTIVE_FAILURES <= 20


def test_live_mode_gives_up_after_repeated_failures():
    import asyncio

    class _AlwaysFails:
        name = "Broken Bench"

        def __init__(self):
            self.attempts = 0

        async def visit(self, when, *, delayed=False):
            self.attempts += 1
            return False

    feeder = _AlwaysFails()
    posted = asyncio.run(
        run_live([feeder], random.Random(0), interval=0.0, jitter=0.0, limit=None)
    )

    assert posted == 0
    # Bounded — and it stopped, rather than raising on the way out.
    assert feeder.attempts == _MAX_CONSECUTIVE_FAILURES
