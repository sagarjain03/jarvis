"""Tests for the generated listening chime."""

import numpy as np

from sounds import chime


def test_chime_is_short_soft_and_clickless():
    tone, sr = chime()
    assert tone.dtype == np.float32
    assert 0.1 < len(tone) / sr < 0.4
    assert 0.05 < np.abs(tone).max() <= 0.3  # soft, never clipping
    assert abs(tone[0]) < 1e-3 and abs(tone[-1]) < 1e-3  # fades in/out: no click
