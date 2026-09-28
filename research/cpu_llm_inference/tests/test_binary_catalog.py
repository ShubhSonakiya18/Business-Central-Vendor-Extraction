"""binary_catalog must never touch the network -- these tests verify that
even the "not found" path is purely local (filesystem checks + a clear
error), never a fetch attempt."""
from __future__ import annotations

import pathlib

import pytest

import binary_catalog as bc


def test_expected_asset_fragment_known_combos():
    assert bc.expected_asset_fragment("windows", "cpu") == "win-cpu"
    assert bc.expected_asset_fragment("linux", "cuda") == "ubuntu-cuda"
    assert bc.expected_asset_fragment("macos", "metal") == "macos-arm64"


def test_expected_asset_fragment_unknown_combo_raises_with_releases_url():
    with pytest.raises(RuntimeError, match="releases"):
        bc.expected_asset_fragment("windows", "rocm-that-doesnt-exist")  # type: ignore[arg-type]


def test_find_server_binary_explicit_path_must_exist(tmp_path):
    missing = tmp_path / "nope" / "llama-server.exe"
    with pytest.raises(RuntimeError, match="not found at explicit path"):
        bc.find_server_binary("windows", "cpu", explicit_path=missing)


def test_find_server_binary_explicit_path_used_when_present(tmp_path):
    exe = tmp_path / "llama-server.exe"
    exe.write_text("fake binary")
    resolved = bc.find_server_binary("windows", "cpu", explicit_path=exe)
    assert resolved.server_path == exe
    assert resolved.backend == "cpu"


def test_find_server_binary_uses_cache_dir_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("TERNARY_BONSAI_HOME", str(tmp_path))
    exe_dir = tmp_path / "bin" / "cpu"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / "llama-server.exe"
    exe.write_text("fake binary")
    resolved = bc.find_server_binary("windows", "cpu")
    assert resolved.server_path == exe


def test_find_server_binary_raises_actionable_error_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setenv("TERNARY_BONSAI_HOME", str(tmp_path))
    with pytest.raises(RuntimeError) as excinfo:
        bc.find_server_binary("windows", "cpu")
    msg = str(excinfo.value)
    assert "win-cpu" in msg  # names the exact asset fragment to download
    assert bc.RELEASES_URL in msg  # and exactly where from
    assert "server_binary" in msg  # and the explicit-override escape hatch


def test_find_server_binary_never_touches_network(monkeypatch, tmp_path):
    """Sanity check on the non-downloading policy itself: patch out the only
    plausible network primitives and confirm nothing calls them."""
    monkeypatch.setenv("TERNARY_BONSAI_HOME", str(tmp_path))
    called = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: called.append(True) or (_ for _ in ()).throw(AssertionError("network touched")),
    )
    with pytest.raises(RuntimeError):
        bc.find_server_binary("windows", "cpu")
    assert called == []


def test_find_model_file_explicit_path(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_text("fake weights")
    assert bc.find_model_file(explicit_path=model) == model


def test_find_model_file_raises_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TERNARY_BONSAI_HOME", str(tmp_path))
    with pytest.raises(RuntimeError) as excinfo:
        bc.find_model_file(quant="PTQ1_0")
    assert "PTQ1_0" in str(excinfo.value)
    assert "huggingface.co" in str(excinfo.value)


def test_find_model_file_defaults_to_ptq1_0_not_pq2_0(monkeypatch, tmp_path):
    """PTQ1_0 has the fast CPU kernel (PR #181); PQ2_0 does not yet -- the
    default must reflect that, not be an arbitrary pick between the two."""
    monkeypatch.setenv("TERNARY_BONSAI_HOME", str(tmp_path))
    with pytest.raises(RuntimeError) as excinfo:
        bc.find_model_file()
    assert "PTQ1_0" in str(excinfo.value)
