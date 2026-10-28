"""Per-tier confidence threshold resolution in ``Config.threshold_for``.

A tier's own setting beats the measured default. Getting it wrong is silent.
The pipeline would escalate more or less often than intended, and nothing
would fail.
"""
import pytest

from raspberry_pi_code.config import Config


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
def test_per_tier_setting_wins_over_the_default(tier):
    cfg = Config(
        tier1_confidence_threshold=0.11,
        tier2_confidence_threshold=0.22,
        tier3_confidence_threshold=0.33,
    )

    assert cfg.threshold_for(tier) == {"local": 0.11, "gpu": 0.22, "cloud": 0.33}[tier]


def test_unknown_tier_name_falls_back_rather_than_raising():
    # A new tier should degrade to a sane bar, not KeyError on the capture path.
    assert Config().threshold_for("quantum") == 0.5

