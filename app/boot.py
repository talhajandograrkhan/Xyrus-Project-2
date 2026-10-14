from core.diag import swallowed as _swallowed
import platform as _platform
import subprocess as _subprocess
import sys as _sys
from pathlib import Path

from core.wake_word import is_ready as wake_is_ready


def _check_runtime_python() -> None:
    """Fail fast with a helpful message when the interpreter is unsupported."""
    v = _sys.version_info[:2]
    if v < (3, 11) or v > (3, 13):
        print(
            f"\n❌ Unsupported Python detected: {_sys.version_info.major}.{_sys.version_info.minor}."
            "\n   MARK LIV requires Python 3.11–3.13."
            "\n   Please launch it with a supported interpreter, for example:"
            "\n     /opt/miniconda3/bin/python3.11 main.py"
            "\n   or:\n     python3.11 main.py"
        )
        raise SystemExit(1)


def _parse_version(version: str):
    """Return the numeric version tuple from a dotted version string."""
    nums = []
    for chunk in version.replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            continue
        nums.append(int(digits))
        if len(nums) == 3:
            break
    return tuple(nums) if nums else (0,)


def _check_qt_compatibility() -> None:
    """Fail with a clear message when an incompatible PyQt build is installed."""
    if _platform.system() != "Darwin":
        return

    mac_version = _platform.mac_ver()[0]
    if not mac_version:
        return

    try:
        major = int(mac_version.split(".", 1)[0])
    except ValueError:
        return

    if major >= 13:
        return

    try:
        from importlib.metadata import version as _pkg_version
        installed_qt = _pkg_version("PyQt6")
    except Exception:
        return

    if _parse_version(installed_qt) >= (6, 8, 0):
        print(
            "\n❌ This system is running macOS 12.x, but PyQt6 >= 6.8 is installed. "
            "Qt 6.8+ requires macOS 13.0+.\n"
            "   Reinstall the compatible version with:\n"
            "     python -m pip install 'PyQt6>=6.6,<6.8'\n"
            "   then launch the app again."
        )
        raise SystemExit(1)


def get_base_dir() -> Path:
    if getattr(_sys, "frozen", False):
        return Path(_sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"


def should_use_wake_word(configured: bool) -> bool:
    """Stay responsive when wake-word was toggled on without a working model."""
    if not configured:
        return False
    if not wake_is_ready():
        print("[JARVIS] Wake word unavailable — falling back to direct listening.")
        try:
            from memory.config_manager import save_wake_word_enabled
            save_wake_word_enabled(False)
        except Exception as _exc:
            _swallowed(__name__, _exc)
        return False
    return True


def build_remote_upload_prompt(file_path: str, file_size_bytes: int | None = None) -> str:
    """Return a stable prompt payload for a file uploaded into the session."""
    path = str(file_path or "")
    name = Path(path).name if path else "uploaded_file"
    size_note = f" | size={file_size_bytes}" if file_size_bytes is not None else ""
    return (
        f"[FILE_UPLOADED] path={path} | name={name}{size_note} | "
        "Briefly tell the user you can see the file and ask what they'd like to do with it."
    )


__all__ = [
    "API_CONFIG_PATH",
    "BASE_DIR",
    "PROMPT_PATH",
    "_check_qt_compatibility",
    "_check_runtime_python",
    "build_remote_upload_prompt",
    "get_base_dir",
    "should_use_wake_word",
]
