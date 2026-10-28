"""The Tier 1 model path default has to name the file ``fetch_models.py`` writes.

When the two disagree, a fresh clone runs ``fetch_models.py``, Tier 1 still
cannot find its model, and every capture falls through to Tier 2.
"""
import importlib.util
import os
from pathlib import Path

import pytest

from raspberry_pi_code.config import Config

_FETCH_MODELS = Path(__file__).resolve().parents[2] / "scripts" / "fetch_models.py"


def _fetch_models_filename() -> str:
    spec = importlib.util.spec_from_file_location("fetch_models", _FETCH_MODELS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tier1,) = [m for m in module.MODELS if m.name == "tier1"]
    return tier1.filename


@pytest.mark.skipif("MODEL_PATH" in os.environ, reason="MODEL_PATH overrides the default")
def test_default_model_path_is_what_fetch_models_writes():
    default = Path(Config().model_path)

    assert default.name == _fetch_models_filename()
    assert default.parent.name == "machine_learning"
