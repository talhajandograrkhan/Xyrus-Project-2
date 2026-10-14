"""
core/sysinfo_mac.py: GPU load and thermal state on macOS, without root.

The HUD read the GPU through NVIDIA's NVML and the temperature through psutil,
which only exists on Linux. On a Mac both came back "N/A". macOS offers neither
number for free, but two tools that need no administrator rights get close:

  ioreg   lists the GPU's performance counters, including "Device Utilization %"
  pmset   reports whether the system is slowing itself down to stay cool

A Mac does not hand out a degrees-Celsius reading without root, so the second
one is reported honestly as a state (OK / Warm / Hot), not as a made-up number.
Every function returns None when it cannot tell; callers show N/A then.
"""
from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

_Run = Callable[..., "subprocess.CompletedProcess"]


def _out(cmd: list[str], run: _Run, timeout: float = 3.0) -> str:
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def parse_gpu_percent(text: str) -> Optional[float]:
    """Highest GPU utilisation figure found in `ioreg -c IOAccelerator` output."""
    found = []
    for pat in (r'"Device Utilization %"\s*=\s*(\d+)',
                r'"GPU Activity\(%\)"\s*=\s*(\d+)',
                r'"Renderer Utilization %"\s*=\s*(\d+)'):
        found += [int(v) for v in re.findall(pat, text)]
    return float(min(100, max(found))) if found else None


def gpu_percent(run: _Run = subprocess.run) -> Optional[float]:
    return parse_gpu_percent(_out(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"], run))


def parse_thermal(pmset_text: str, sysctl_text: str = "") -> Optional[tuple[str, int]]:
    """('OK' | 'Warm' | 'Hot', 0-100 pressure) from `pmset -g therm`, falling back
    to Intel's cpu_thermal_level. None when neither says anything."""
    limits = [int(v) for v in re.findall(r"(?:CPU_Speed_Limit|CPU_Scheduler_Limit)\s*=\s*(\d+)", pmset_text)]
    if limits:
        slow = 100 - min(limits)                      # percent of speed given up to stay cool
        return (("OK", max(5, slow)) if slow < 10 else
                ("Warm", min(100, 40 + slow)) if slow < 40 else ("Hot", min(100, 60 + slow)))
    if re.search(r"no thermal warning level has been recorded", pmset_text, re.I):
        return ("OK", 20)
    m = re.search(r"(\d+)", sysctl_text or "")
    if m:
        level = int(m.group(1))
        return ("OK", 20) if level == 0 else (("Warm", 55) if level < 50 else ("Hot", 85))
    return None


def thermal_state(run: _Run = subprocess.run) -> Optional[tuple[str, int]]:
    pm = _out(["pmset", "-g", "therm"], run)
    sc = "" if pm else _out(["sysctl", "-n", "machdep.xcpm.cpu_thermal_level"], run)
    return parse_thermal(pm, sc)
