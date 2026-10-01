"""No real process is ever spawned and no real HTTP call is ever made here --
subprocess.Popen and requests.get/post are fully mocked, so these tests pass
identically regardless of whether llama-server or any GGUF file actually
exists on the machine running them."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

import binary_catalog
import config as config_module
import runtime_manager as rm
from device_capabilities import MachineCapabilities


@pytest.fixture
def fixed_capabilities(monkeypatch):
    """Pin LlamaServerConfig's hardware auto-detection to a known, fake CPU-
    only machine -- so config construction is deterministic in tests."""
    caps = MachineCapabilities(os_name="linux", arch="x64", gpu_backends=[], cpu_threads=6)
    monkeypatch.setattr(config_module.MachineCapabilities, "probe", classmethod(lambda cls: caps))
    return caps


@pytest.fixture
def cfg(fixed_capabilities, tmp_path):
    model = tmp_path / "model.gguf"
    model.write_text("fake")
    server = tmp_path / "llama-server"
    server.write_text("fake")
    return config_module.LlamaServerConfig(
        model_path=model, server_binary=server, port=18091,
    )


class FakeProcess:
    def __init__(self, healthy_after_polls: int = 0, exits_with: int | None = None):
        self._polls = 0
        self._healthy_after_polls = healthy_after_polls
        self._exits_with = exits_with
        self.terminated = False
        self.killed = False
        self.stdout = SimpleNamespace(readlines=lambda: ["line1\n", "line2\n"])

    def poll(self):
        if self._exits_with is not None:
            return self._exits_with
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        if self.killed or self.terminated:
            return 0
        raise Exception("wait called before terminate/kill")


def test_build_command_uses_resolved_backend_and_threads(cfg):
    server = rm.LlamaServerProcess(cfg)
    command = server._build_command()
    assert "-t" in command
    assert command[command.index("-t") + 1] == "6"  # from fixed_capabilities.cpu_threads
    assert "-ngl" in command
    assert command[command.index("-ngl") + 1] == "0"  # cpu backend -> 0 gpu layers
    assert "--port" in command
    assert command[command.index("--port") + 1] == "18091"


def test_start_succeeds_when_health_check_returns_200(monkeypatch, cfg):
    fake_proc = FakeProcess()
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: fake_proc)

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: FakeResponse())

    server = rm.LlamaServerProcess(cfg)
    result = server.start()
    assert result is server
    assert server.is_running is True


def test_start_raises_with_stderr_tail_when_process_exits_early(monkeypatch, cfg):
    fake_proc = FakeProcess(exits_with=1)
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: fake_proc)

    server = rm.LlamaServerProcess(cfg)
    with pytest.raises(rm.LlamaServerStartupError, match="exited with code 1"):
        server.start()


def test_start_times_out_and_stops_process(monkeypatch, cfg):
    fake_proc = FakeProcess()  # never exits, never healthy
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: fake_proc)
    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: (_ for _ in ()).throw(rm.requests.RequestException()))
    monkeypatch.setattr(rm.time, "sleep", lambda s: None)  # don't actually wait in tests

    cfg.startup_timeout_s = 0.01
    server = rm.LlamaServerProcess(cfg)
    with pytest.raises(rm.LlamaServerStartupError, match="did not become healthy"):
        server.start()
    assert fake_proc.terminated is True


def test_stop_escalates_to_kill_on_timeout(monkeypatch, cfg):
    fake_proc = FakeProcess()
    fake_proc.wait = lambda timeout=None: (_ for _ in ()).throw(rm.subprocess.TimeoutExpired("x", 1)) if not fake_proc.killed else 0

    server = rm.LlamaServerProcess(cfg)
    server._process = fake_proc
    server.stop()
    assert fake_proc.terminated is True
    assert fake_proc.killed is True


def test_stop_is_a_noop_when_never_started(cfg):
    server = rm.LlamaServerProcess(cfg)
    server.stop()  # must not raise


def test_context_manager_starts_and_stops(monkeypatch, cfg):
    fake_proc = FakeProcess()
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: fake_proc)

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: FakeResponse())

    with rm.LlamaServerProcess(cfg) as server:
        assert server.is_running is True
    assert fake_proc.terminated is True


def test_double_start_raises(monkeypatch, cfg):
    fake_proc = FakeProcess()
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: fake_proc)

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: FakeResponse())

    server = rm.LlamaServerProcess(cfg)
    server.start()
    with pytest.raises(RuntimeError, match="already started"):
        server.start()
