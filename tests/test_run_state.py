"""Run-state persistence and the run_id path guard.

Runs are keyed by an id that arrives from the URL and is then used as a
filesystem path segment, so the id format check is load-bearing: without it a
crafted id walks out of the outputs directory.
"""

import json
import shutil

import pytest

import app as web


@pytest.fixture
def run_id():
    # Contains hex letters so that case-sensitivity assertions are meaningful.
    rid = "abcdef0123"
    yield rid
    shutil.rmtree(web.OUTPUT_DIR / rid, ignore_errors=True)


class TestRoundTrip:
    def test_saved_state_reads_back_identical(self, run_id):
        state = {
            "fields": {"pan": {"value": "AABCM7980K", "confidence": 1.0}},
            "needs_review": [],
            "summary": {"total_fields": 24, "filled": 19},
            "files": {"json": "outputs/x/result.json"},
            "timings": {"total": 653.6},
        }
        web._save_run(run_id, state)
        assert web._load_run(run_id) == state

    def test_state_lands_under_the_run_directory(self, run_id):
        web._save_run(run_id, {"files": {}})
        path = web.OUTPUT_DIR / run_id / "run_state.json"
        assert path.is_file()
        assert json.loads(path.read_text(encoding="utf-8")) == {"files": {}}

    def test_survives_a_process_restart(self, run_id):
        """The whole point of moving off a module-level dict: a run written by
        one process is readable by another."""
        web._save_run(run_id, {"files": {"json": "x"}})
        importlib_reloaded = __import__("importlib").reload(web)
        assert importlib_reloaded._load_run(run_id) == {"files": {"json": "x"}}


class TestUnknownRuns:
    def test_never_written_returns_none(self):
        assert web._load_run("aaaaaaaaaa") is None

    def test_corrupt_state_file_returns_none(self, run_id):
        path = web.OUTPUT_DIR / run_id / "run_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        assert web._load_run(run_id) is None


class TestRunIdGuard:
    @pytest.mark.parametrize("bad_id", [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "abc/def",
        "NOTHEXVAL",
        "ABCDEF0123",      # uppercase hex is not the generated form
        "abcdef012",       # too short
        "abcdef01234",     # too long
        "",
        ".",
        "..",
    ])
    def test_rejects_anything_but_a_generated_id(self, bad_id):
        assert web._load_run(bad_id) is None

    def test_traversal_cannot_read_a_file_outside_outputs(self, tmp_path):
        """The assertion that actually exercises the guard.

        Returning None for a path that does not exist proves nothing -- every
        rejected id would pass that way. So plant a readable run_state.json
        outside the outputs directory and confirm a traversal id still cannot
        reach it. Delete the guard and this test fails; the others do not.
        """
        outside = web.OUTPUT_DIR.parent / "pytest_outside_run"
        outside.mkdir(parents=True, exist_ok=True)
        try:
            (outside / "run_state.json").write_text(
                json.dumps({"secret": "should never be served"}), encoding="utf-8"
            )
            traversal_id = f"../{outside.name}"

            # Without the guard this resolves and returns the planted content.
            assert web._load_run(traversal_id) is None
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_case_variant_cannot_reach_a_real_run(self, run_id):
        """Windows paths are case-insensitive, so an uppercased id would reach
        the same directory on this platform if the format check were dropped."""
        web._save_run(run_id, {"files": {"json": "x"}})
        assert web._load_run(run_id.upper()) is None

    def test_accepts_the_format_the_app_generates(self, run_id):
        web._save_run(run_id, {"files": {}})
        assert web._load_run(run_id) is not None

    def test_generated_ids_match_the_guard(self):
        """uuid4().hex[:10] is what the route creates; the guard must accept it."""
        import re
        import uuid

        for _ in range(50):
            generated = uuid.uuid4().hex[:10]
            assert re.fullmatch(r"[0-9a-f]{10}", generated), generated
