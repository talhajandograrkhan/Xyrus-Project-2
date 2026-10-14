from __future__ import annotations

from core.diag import swallowed as _swallowed
import io
import json
import re
from datetime import datetime
from pathlib import Path
import sys

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
PROFILE_PATH = BASE_DIR / "memory" / "voice_profiles.json"
UNKNOWN_DIR = BASE_DIR / "memory" / "unknown_people"
FACE_PROFILE_PATH = BASE_DIR / "memory" / "face_profiles.json"
FACE_UNKNOWN_DIR = BASE_DIR / "memory" / "unknown_faces"


def _normalize_name(raw: str | None) -> str:
    text = (raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "Unknown"
    return text.title()


def _coerce_samples(samples):
    """Return a list of 1-D PCM sample arrays for a single voice recording or a list thereof."""
    if samples is None:
        return []
    if isinstance(samples, np.ndarray):
        if samples.ndim == 1:
            return [np.asarray(samples, dtype=np.float32)]
        return [np.asarray(part, dtype=np.float32) for part in samples]
    if isinstance(samples, (list, tuple)):
        if not samples:
            return []
        first = samples[0]
        if isinstance(first, (np.ndarray, list, tuple)):
            return [np.asarray(part, dtype=np.float32) for part in samples]
        return [np.asarray(samples, dtype=np.float32)]
    return [np.asarray(samples, dtype=np.float32)]


def _average_fingerprint(samples_list) -> list[float]:
    """Average multiple per-sample fingerprints into a single stable profile signature."""
    arrays = [np.asarray(_fingerprint(s), dtype=np.float32) for s in samples_list if np.asarray(s).size]
    if not arrays:
        return []
    avg = np.mean(np.vstack(arrays), axis=0)
    return avg.astype(float).tolist()


def _fingerprint(samples, sr: int = 16000) -> np.ndarray:
    """Return a compact, deterministic voice fingerprint for a PCM block.

    The goal is not full biometric accuracy; it is a stable similarity signal
    that recognises the same speaker again while separating a different voice
    from random noise. A small set of RMS, zero-crossing and spectral features is
    enough for that kind of repeated-speaker detection in a desktop assistant.
    """
    arr = np.asarray(samples)
    if arr.size == 0:
        return np.zeros(12, dtype=np.float32)
    x = np.asarray(arr, dtype=np.float32).ravel()
    if x.size == 0:
        return np.zeros(12, dtype=np.float32)

    x = x / max(np.max(np.abs(x)), 1.0)
    rms = float(np.sqrt(np.mean(x * x)))
    mean_abs = float(np.mean(np.abs(x)))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x))) > 0)) if x.size > 1 else 0.0

    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    total = float(np.sum(spec) + 1e-8)
    centroid = float(np.sum(freqs * spec) / total)
    low = spec[(freqs >= 80) & (freqs < 400)]
    mid = spec[(freqs >= 400) & (freqs < 2000)]
    high = spec[(freqs >= 2000) & (freqs < 8000)]
    low_ratio = float(np.sum(low) / total)
    mid_ratio = float(np.sum(mid) / total)
    high_ratio = float(np.sum(high) / total)
    slope = float(np.mean(np.abs(np.diff(x))))

    return np.array(
        [
            rms,
            mean_abs,
            zcr,
            centroid / sr,
            low_ratio,
            mid_ratio,
            high_ratio,
            slope,
            float(np.percentile(np.abs(x), 25)),
            float(np.percentile(np.abs(x), 50)),
            float(np.percentile(np.abs(x), 75)),
        ],
        dtype=np.float32,
    )


class VoiceProfileStore:
    """Small, disk-backed speaker profile store for known-repeat voices."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else PROFILE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._profiles = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"known": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                known = data.get("known", {})
                if isinstance(known, dict):
                    return {"known": known}
        except Exception as _exc:
            _swallowed(__name__, _exc)
        return {"known": {}}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._profiles, indent=2, ensure_ascii=False), encoding="utf-8")

    def register_voice(self, name: str, samples, introduction: str | None = None, image_path: str | None = None) -> str:
        normalized = _normalize_name(name)
        sample_list = _coerce_samples(samples)
        if not sample_list:
            return normalized

        fp_list = [_fingerprint(sample).astype(float).tolist() for sample in sample_list]
        self._profiles.setdefault("known", {})
        existing = self._profiles["known"].get(normalized, {})
        old = existing.get("samples", [])
        if isinstance(old, list) and old and isinstance(old[0], list):
            merged = old + fp_list
        elif existing.get("fingerprint"):
            merged = [existing.get("fingerprint", [])] + fp_list
        else:
            merged = fp_list

        # Keep the last few samples only; a few enrollment clips are enough for
        # stable recognition and keep the disk footprint small.
        merged = merged[-12:]
        profile = {
            "samples": merged,
            "fingerprint": _average_fingerprint(merged),
            "introduction": introduction or existing.get("introduction", ""),
            "image_path": image_path or existing.get("image_path", ""),
            "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._profiles["known"][normalized] = profile
        self._save()
        return normalized

    def recognize_voice(self, samples) -> tuple[str | None, float]:
        fp = _fingerprint(samples).astype(float)
        best_name = None
        best_score = float("inf")

        for name, profile in self._profiles.get("known", {}).items():
            sample_vectors = profile.get("samples")
            if not isinstance(sample_vectors, list) or not sample_vectors:
                legacy = profile.get("fingerprint")
                if isinstance(legacy, list):
                    sample_vectors = [legacy]
                else:
                    continue

            profile_best = float("inf")
            for values_raw in sample_vectors:
                values = np.asarray(values_raw, dtype=np.float32)
                if values.size == 0:
                    continue
                score = float(np.linalg.norm(values - fp) / (len(values) ** 0.5 + 1e-6))
                profile_best = min(profile_best, score)

            if profile_best < best_score:
                best_score = profile_best
                best_name = name

        # A practical threshold for a desktop app: same voice is close, random noise is not.
        if best_name is not None and best_score <= 0.18:
            return best_name, best_score
        return None, best_score

    def has_known_voices(self) -> bool:
        return bool(self._profiles.get("known", {}))

    def known_names(self) -> list[str]:
        return sorted(self._profiles.get("known", {}).keys())

    def extract_intro_name(self, text: str) -> str | None:
        candidate = (text or "").strip()
        if not candidate:
            return None
        patterns = [
            r"\b(?:i\s*am|i'm|my\s+name\s+is|call\s+me|this\s+is)\s+([A-Za-z][A-Za-z'\- ]{1,30})",
            r"\b([A-Za-z][A-Za-z'\- ]{1,30})\s+here\b",
        ]
        for pat in patterns:
            match = re.search(pat, candidate, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" ,.!?")
                if value and len(value) > 1:
                    return _normalize_name(value)
        return None

    def save_unknown_person_image(self, image_bytes: bytes, suffix: str = "unknown") -> str:
        UNKNOWN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        target = UNKNOWN_DIR / f"{suffix}_{stamp}.jpg"
        target.write_bytes(image_bytes)
        return str(target)


class FaceProfileStore:
    """Very small face identity store for the camera-based stranger gate."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else FACE_PROFILE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._profiles = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"known": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                known = data.get("known", {})
                if isinstance(known, dict):
                    return {"known": known}
        except Exception as _exc:
            _swallowed(__name__, _exc)
        return {"known": {}}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._profiles, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _decode_image(image_bytes: bytes | bytearray | memoryview | str | None):
        if image_bytes is None:
            return None
        if isinstance(image_bytes, (bytes, bytearray, memoryview)):
            try:
                arr = np.frombuffer(bytes(image_bytes), dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if cv2 is not None else None
                if img is not None:
                    return img
            except Exception as _exc:
                _swallowed(__name__, _exc)
            return None
        if isinstance(image_bytes, str):
            p = Path(image_bytes)
            if p.exists():
                try:
                    return cv2.imread(str(p), cv2.IMREAD_COLOR) if cv2 is not None else None
                except Exception:
                    return None
        return None

    @staticmethod
    def _image_to_embedding(image) -> np.ndarray:
        if image is None:
            return np.zeros(64, dtype=np.float32)
        if isinstance(image, (bytes, bytearray, memoryview, str)):
            image = FaceProfileStore._decode_image(image)
        if image is None:
            return np.zeros(64, dtype=np.float32)
        if isinstance(image, np.ndarray):
            img = image
        else:
            return np.zeros(64, dtype=np.float32)

        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if cv2 is not None else img.mean(axis=2).astype(np.uint8)
        else:
            gray = img.astype(np.uint8)

        # Resize to a compact fixed vector so repeated true matches stay stable while
        # random faces and the wrong camera angle fall away.
        small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA) if cv2 is not None else gray[:32, :32]
        flat = small.astype(np.float32).ravel()
        if flat.size == 0:
            return np.zeros(64, dtype=np.float32)
        flat = flat / (np.std(flat) + 1e-6)
        return flat[:64]

    def register_face(self, name: str, image_bytes, introduction: str | None = None, image_path: str | None = None) -> str:
        normalized = _normalize_name(name)
        emb = self._image_to_embedding(image_bytes).astype(float).tolist()
        self._profiles.setdefault("known", {})
        self._profiles["known"][normalized] = {
            "embedding": emb,
            "introduction": introduction or "",
            "image_path": image_path or "",
            "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save()
        return normalized

    def recognize_face(self, image_bytes) -> tuple[str | None, float]:
        emb = self._image_to_embedding(image_bytes).astype(float)
        best_name = None
        best_score = float("inf")

        for name, profile in self._profiles.get("known", {}).items():
            values = np.asarray(profile.get("embedding", []), dtype=np.float32)
            if values.size == 0:
                continue
            score = float(np.linalg.norm(values - emb) / (len(values) ** 0.5 + 1e-6))
            if score < best_score:
                best_score = score
                best_name = name

        # Same face remains close across camera angle and small lighting shifts;
        # a different person should sit noticeably farther away.
        if best_name is not None and best_score <= 0.25:
            return best_name, best_score
        return None, best_score

    def known_names(self) -> list[str]:
        return sorted(self._profiles.get("known", {}).keys())

    def has_known_faces(self) -> bool:
        return bool(self._profiles.get("known", {}))

    def save_unknown_face_image(self, image_bytes: bytes, suffix: str = "unknown") -> str:
        FACE_UNKNOWN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        target = FACE_UNKNOWN_DIR / f"{suffix}_{stamp}.jpg"
        target.write_bytes(image_bytes)
        return str(target)


__all__ = [
    "VoiceProfileStore",
    "FaceProfileStore",
    "PROFILE_PATH",
    "UNKNOWN_DIR",
    "FACE_PROFILE_PATH",
    "FACE_UNKNOWN_DIR",
    "_fingerprint",
]
