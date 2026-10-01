"""Typed configuration for the inference server, in the project's own
pydantic-settings style (see backend/app/config/config.py) so this module
drops in cleanly if/when it moves into the app proper.

Every field with a hardware-shaped default (threads, gpu layers, backend)
resolves lazily against MachineCapabilities.probe() rather than being
hardcoded at class-definition time -- so importing this module on ANY
machine is safe and never bakes in the machine that happened to import it.
"""
from __future__ import annotations

import pathlib
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from device_capabilities import Backend, MachineCapabilities

BackendChoice = Literal["auto", "cpu", "cuda", "vulkan", "rocm", "metal"]


class LlamaServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TERNARY_BONSAI_", extra="ignore")

    # -- what to run ----------------------------------------------------
    model_path: Optional[pathlib.Path] = None       # None -> resolved via binary_catalog.find_model_file
    quant: Literal["PTQ1_0", "PQ2_0"] = "PTQ1_0"     # PTQ1_0 has the fast CPU kernel (see binary_catalog docstring)
    server_binary: Optional[pathlib.Path] = None     # None -> resolved via binary_catalog.find_server_binary

    # -- how to run it ----------------------------------------------------
    backend: BackendChoice = "auto"                  # "auto" = best GPU backend this machine has, else cpu
    n_threads: Optional[int] = None                  # None -> device_capabilities.default_thread_count()
    n_gpu_layers: Optional[int] = None                # None -> -1 (all) if backend!=cpu, else 0
    context_length: int = 4096                        # deliberately far below the model's 262K max -- see README
    host: str = "127.0.0.1"
    port: int = 8091                                  # distinct from the FastAPI app's own 8000
    startup_timeout_s: float = 120.0

    @model_validator(mode="after")
    def _fill_hardware_defaults(self) -> "LlamaServerConfig":
        """Resolve every "auto"/None hardware-shaped field against what THIS
        machine actually reports, once, at config-construction time -- not
        against a value baked in when this class was written."""
        caps = MachineCapabilities.probe()
        resolved_backend = caps.resolve_backend(self.backend)  # type: ignore[arg-type]
        object.__setattr__(self, "_resolved_backend", resolved_backend)
        object.__setattr__(self, "_capabilities", caps)
        if self.n_threads is None:
            object.__setattr__(self, "n_threads", caps.cpu_threads)
        if self.n_gpu_layers is None:
            object.__setattr__(self, "n_gpu_layers", -1 if resolved_backend != "cpu" else 0)
        return self

    @property
    def resolved_backend(self) -> Backend:
        return self._resolved_backend  # type: ignore[attr-defined,return-value]

    @property
    def capabilities(self) -> MachineCapabilities:
        return self._capabilities  # type: ignore[attr-defined,return-value]
