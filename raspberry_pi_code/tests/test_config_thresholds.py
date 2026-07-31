"""Per-tier confidence threshold resolution in ``Config.threshold_for``.

The precedence rule is the whole point of this file: a tier's own setting beats
the legacy global, which beats the measured default. Getting it wrong is silent
— the pipeline would simply escalate more or less often than intended, and
nothing would fail.
"""
import pytest

from raspberry_pi_code.config import DEFAULT_TIER_THRESHOLDS, Config


def test_defaults_differ_per_tier():
    cfg = Config()

    assert cfg.threshold_for("local") == 0.85
    assert cfg.threshold_for("gpu") == 0.60
    assert cfg.threshold_for("cloud") == 0.50


def test_tier1_default_is_stricter_than_tier2():
    """The measurement's central finding, pinned.

    Tier 1 is both less accurate and less honest about being wrong (mean
    confidence 0.368 when wrong, against Tier 2's 0.242), so it has to clear a
    higher bar. If a future model swap inverts these, that is a decision worth
    making deliberately rather than inheriting.
    """
    cfg = Config()

    assert cfg.threshold_for("local") > cfg.threshold_for("gpu")


@pytest.mark.parametrize("tier", ["local", "gpu", "cloud"])
def test_per_tier_setting_wins_over_everything(tier):
    cfg = Config(
        tier1_confidence_threshold=0.11,
        tier2_confidence_threshold=0.22,
        tier3_confidence_threshold=0.33,
        confidence_threshold=0.99,
    )

    assert cfg.threshold_for(tier) == {"local": 0.11, "gpu": 0.22, "cloud": 0.33}[tier]


def test_legacy_global_applies_where_no_per_tier_value_is_set():
    # An operator who pinned CONFIDENCE_THRESHOLD did so for a reason; a new
    # default must not quietly override it.
    cfg = Config(confidence_threshold=0.4)

    assert cfg.threshold_for("local") == 0.4
    assert cfg.threshold_for("gpu") == 0.4
    assert cfg.threshold_for("cloud") == 0.4


def test_legacy_global_fills_only_the_gaps():
    cfg = Config(confidence_threshold=0.4, tier1_confidence_threshold=0.9)

    assert cfg.threshold_for("local") == 0.9
    assert cfg.threshold_for("gpu") == 0.4


def test_unset_global_leaves_the_measured_defaults_in_place():
    assert Config().confidence_threshold is None
    assert Config().threshold_for("local") == DEFAULT_TIER_THRESHOLDS["local"]


def test_unknown_tier_name_falls_back_rather_than_raising():
    # A new tier should degrade to a sane bar, not KeyError on the capture path.
    assert Config().threshold_for("quantum") == 0.5


@pytest.mark.parametrize(
    "cfg, expected",
    [
        (Config(), False),
        (Config(confidence_threshold=0.5), True),
        # Fully overridden per tier: the global is inert, so there is nothing to warn about.
        (
            Config(
                confidence_threshold=0.5,
                tier1_confidence_threshold=0.8,
                tier2_confidence_threshold=0.6,
                tier3_confidence_threshold=0.5,
            ),
            False,
        ),
        (Config(confidence_threshold=0.5, tier1_confidence_threshold=0.8), True),
    ],
)
def test_legacy_warning_fires_only_when_the_global_actually_displaces_a_default(cfg, expected):
    assert cfg.uses_legacy_global_threshold() is expected
