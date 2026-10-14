"""Audio-level and viseme helpers used by the runtime audio pipeline."""

import numpy as np

_LEVEL_FLOOR = 60.0
_LEVEL_FULL = 2600.0


def pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


def pcm_visemes(samples, sr: int = 24000):
    """Return viseme frames from PCM audio, using the same simplified logic as the runtime."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size < 1024:
            return []
        win = np.hanning(1024).astype(np.float32)
        freqs = np.fft.rfftfreq(1024, 1.0 / sr)
        b_f1_lo = (freqs >= 150) & (freqs < 450)
        b_f1_hi = (freqs >= 450) & (freqs < 1100)
        b_f2_bk = (freqs >= 600) & (freqs < 1300)
        b_f2_fr = (freqs >= 1700) & (freqs < 3200)
        b_hiss = (freqs >= 3800) & (freqs < 8000)

        out = []
        for start in range(0, x.size, 480):
            level = pcm_level(x[start:start + 480])
            seg = x[start:start + 1024]
            if seg.size < 1024:
                seg = np.concatenate([seg, np.zeros(1024 - seg.size, dtype=np.float32)])
            if level <= 0.0:
                out.append((0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft((seg - seg.mean()) * win))
            f1l, f1h = float(mag[b_f1_lo].sum()), float(mag[b_f1_hi].sum())
            f2b, f2f = float(mag[b_f2_bk].sum()), float(mag[b_f2_fr].sum())
            hiss = float(mag[b_hiss].sum())
            openness = f1h / (f1l + f1h + 1e-6)
            width = (f2f - f2b) / (f2f + f2b + 1e-6)
            width *= (1.0 - openness) ** 0.8
            h = hiss / (f1l + f1h + f2b + f2f + hiss + 1e-6)
            openness *= 1.0 - 0.65 * min(1.0, h * 2.5)
            out.append((
                level,
                float(min(1.0, max(0.0, openness))),
                float(min(1.0, max(-1.0, width))),
            ))
        return out
    except Exception:
        return []


class AudioPipeline:
    """Container that exposes the audio pipeline API to the rest of the app."""

    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    def level(self, samples):
        return pcm_level(samples)

    def visemes(self, samples, sr: int = 24000):
        return pcm_visemes(samples, sr=sr)


__all__ = ["AudioPipeline", "pcm_level", "pcm_visemes"]
