"""Portable machine/software inspection -- no hardcoded CPU model, core count,
or OS assumptions. Every value here is read from the live system at run time,
so this script produces correct output on whatever machine runs it, not just
the one it was written on.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _windows_wmi_field(cim_class: str, field: str) -> str | None:
    out = _run([
        "powershell", "-NoProfile", "-Command",
        f"(Get-CimInstance {cim_class}).{field}",
    ])
    return out.strip() if out else None


@dataclass
class MachineInfo:
    os_name: str
    os_version: str
    os_build: str | None
    cpu_model: str | None
    cpu_manufacturer: str | None
    cpu_arch: str
    cpu_physical_cores: int | None
    cpu_logical_cores: int
    cpu_max_clock_mhz: str | None
    ram_total_gb: float | None
    ram_free_gb_at_start: float | None
    python_version: str
    nvidia_gpu_present: bool
    gpu_devices: list[str]


def gather_windows() -> MachineInfo:
    cpu_name = _windows_wmi_field("Win32_Processor", "Name")
    cpu_mfr = _windows_wmi_field("Win32_Processor", "Manufacturer")
    phys_cores = _windows_wmi_field("Win32_Processor", "NumberOfCores")
    max_clock = _windows_wmi_field("Win32_Processor", "MaxClockSpeed")
    os_caption = _windows_wmi_field("Win32_OperatingSystem", "Caption")
    os_version = _windows_wmi_field("Win32_OperatingSystem", "Version")
    os_build = _windows_wmi_field("Win32_OperatingSystem", "BuildNumber")

    ram_total = _run([
        "powershell", "-NoProfile", "-Command",
        "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2)",
    ])
    ram_free = _run([
        "powershell", "-NoProfile", "-Command",
        "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)",
    ])

    nvidia_present = shutil.which("nvidia-smi") is not None
    if nvidia_present:
        # presence of the tool alone isn't proof of a working GPU -- confirm it
        # actually reports a device
        out = _run(["nvidia-smi", "-L"])
        nvidia_present = bool(out and out.strip())

    gpu_out = _run([
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join '|'",
    ])
    gpu_devices = [g.strip() for g in (gpu_out or "").split("|") if g.strip()]

    return MachineInfo(
        os_name=os_caption or platform.system(),
        os_version=os_version or platform.version(),
        os_build=os_build,
        cpu_model=cpu_name,
        cpu_manufacturer=cpu_mfr,
        cpu_arch=platform.machine(),
        cpu_physical_cores=int(phys_cores) if phys_cores and phys_cores.isdigit() else None,
        cpu_logical_cores=os.cpu_count() or 0,
        cpu_max_clock_mhz=max_clock,
        ram_total_gb=float(ram_total) if ram_total else None,
        ram_free_gb_at_start=float(ram_free) if ram_free else None,
        python_version=sys.version,
        nvidia_gpu_present=nvidia_present,
        gpu_devices=gpu_devices,
    )


def gather() -> MachineInfo:
    """Dispatch by OS -- Windows is fully implemented (this benchmark's
    actual run environment); Linux/macOS use portable fallbacks (os.cpu_count,
    platform module, /proc or sysctl where available) so this file doesn't
    silently fail on another OS, even though this run's real results are
    Windows-specific."""
    if platform.system() == "Windows":
        return gather_windows()

    ram_total_gb = None
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        ram_total_gb = round(kb / (1024 * 1024), 2)
                        break
        except OSError:
            pass

    return MachineInfo(
        os_name=platform.system(),
        os_version=platform.version(),
        os_build=None,
        cpu_model=platform.processor() or None,
        cpu_manufacturer=None,
        cpu_arch=platform.machine(),
        cpu_physical_cores=None,
        cpu_logical_cores=os.cpu_count() or 0,
        cpu_max_clock_mhz=None,
        ram_total_gb=ram_total_gb,
        ram_free_gb_at_start=None,
        python_version=sys.version,
        nvidia_gpu_present=shutil.which("nvidia-smi") is not None,
        gpu_devices=[],
    )


def current_free_ram_gb() -> float | None:
    """Re-sample free RAM at any point during the run (used before/after
    model load to detect memory pressure -- see CPU_BENCHMARK_REPORT.md
    section 9)."""
    if platform.system() != "Windows":
        return None
    out = _run([
        "powershell", "-NoProfile", "-Command",
        "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)",
    ])
    return float(out) if out else None


if __name__ == "__main__":
    print(json.dumps(asdict(gather()), indent=2))
