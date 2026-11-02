"""Small generated sounds (no audio files to ship)."""

from __future__ import annotations

import numpy as np


def chime(sample_rate: int = 24000) -> tuple[np.ndarray, int]:
    """Soft two-note rising "ding" that means "your turn, I'm listening"."""
    note = 0.09  # seconds per note
    t = np.arange(int(sample_rate * note)) / sample_rate
    tone = np.concatenate([np.sin(2 * np.pi * f * t) for f in (880.0, 1320.0)])
    fade = np.sin(np.linspace(0, np.pi, tone.size))  # smooth in/out, no clicks
    return (tone * fade * 0.2).astype(np.float32), sample_rate
