"""Tests for rman_denoiser.core.runner."""
from __future__ import annotations
from rman_denoiser.core import runner
from rman_denoiser.core.job import DenoiseJob


def test_build_run_argv_json_mode():
    job = DenoiseJob(inputs=["a.exr"], output_dir="/out", tiles=1024, frames="1-3")
    argv = runner.build_run_argv("denoise_batch.exe", "/out/cfg.json", job)
    assert argv[0] == "denoise_batch.exe"
    assert "-j" in argv and "/out/cfg.json" in argv
    i = argv.index("--tiles"); assert argv[i+1:i+3] == ["1024", "1024"]
    assert "--frame-include" in argv and "1-3" in argv
    assert "-p" in argv


def test_build_run_argv_no_tiles():
    job = DenoiseJob(inputs=["a.exr"], output_dir="/out")
    argv = runner.build_run_argv("denoise_batch.exe", "/out/cfg.json", job)
    assert "--tiles" not in argv and "--frame-include" not in argv


# ── Step 2: run() with progress parsing ───────────────────────────────────────

class _FakeProc:
    def __init__(self, lines, code=0):
        self.stdout = iter(lines)
        self._code = code

    def wait(self):
        return self._code


def test_run_parses_progress(monkeypatch):
    seen = []
    lines = ["R90000 something\n", "25%\n", "noise\n", "100%\n"]
    monkeypatch.setattr(runner.subprocess, "Popen", lambda argv, **kw: _FakeProc(lines))
    code = runner.run(["denoise_batch.exe", "-j", "c.json"], on_progress=lambda p: seen.append(p))
    assert code == 0 and seen == [25, 100]


def test_denoise_orchestrates(monkeypatch, tmp_path):
    from rman_denoiser.core import config as cfgmod
    from rman_denoiser.core.job import DenoiseJob
    monkeypatch.setattr(cfgmod, "generate_config",
                        lambda exe, job, **k: str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text('{"settings": {}, "passes": []}')
    captured = {}

    def fake_run(argv, **k):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), selected_aovs=["L_sun"])
    assert runner.denoise("denoise_batch.exe", job) == 0
    assert "-j" in captured["argv"]
    assert (tmp_path / "rmandenoise_pruned.json").is_file()


# ── parse_frame_range ──────────────────────────────────────────────────────────

def test_parse_frame_range_single():
    assert runner.parse_frame_range("1001") == [1001]

def test_parse_frame_range_range():
    assert runner.parse_frame_range("1001-1003") == [1001, 1002, 1003]

def test_parse_frame_range_multi_segment():
    assert runner.parse_frame_range("1001-1003,1005") == [1001, 1002, 1003, 1005]

def test_parse_frame_range_deduplicates():
    assert runner.parse_frame_range("1001-1003,1002") == [1001, 1002, 1003]

def test_parse_frame_range_bad_input_raises_valueerror():
    import pytest
    with pytest.raises(ValueError, match="Bad frame spec"):
        runner.parse_frame_range("-1001")


# ── frames_from_glob ───────────────────────────────────────────────────────────

def test_frames_from_glob_hash_pattern(tmp_path):
    for name in ["render.1001.exr", "render.1002.exr", "render.1003.exr"]:
        (tmp_path / name).touch()
    assert runner.frames_from_glob(str(tmp_path / "render.####.exr")) == [1001, 1002, 1003]

def test_frames_from_glob_star_pattern(tmp_path):
    for name in ["render.1001.exr", "render.1002.exr"]:
        (tmp_path / name).touch()
    assert runner.frames_from_glob(str(tmp_path / "*.exr")) == [1001, 1002]

def test_frames_from_glob_no_matches(tmp_path):
    assert runner.frames_from_glob(str(tmp_path / "*.exr")) == []

def test_frames_from_glob_skips_non_frame_exrs(tmp_path):
    (tmp_path / "beauty.exr").touch()          # no frame number
    (tmp_path / "render.1001.exr").touch()
    result = runner.frames_from_glob(str(tmp_path / "*.exr"))
    assert result == [1001]


# ── denoise_frames ─────────────────────────────────────────────────────────────

def _patch_config(monkeypatch, tmp_path):
    """Patch generate_config to write an empty config and return its path."""
    from rman_denoiser.core import config as cfgmod
    cfg_path = str(tmp_path / "config.json")
    monkeypatch.setattr(cfgmod, "generate_config", lambda exe, job, **k: cfg_path)
    (tmp_path / "config.json").write_text('{"settings": {}, "passes": []}')


def test_denoise_frames_calls_run_per_frame(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1003")
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 3
    for i, n in enumerate([1001, 1002, 1003]):
        idx = calls[i].index("--frame-include")
        assert calls[i][idx + 1] == str(n)


def test_denoise_frames_progress_reported_per_frame(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "run", lambda argv, **k: 0)
    reported = []
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1002")
    runner.denoise_frames("db.exe", job, on_progress=reported.append)
    assert reported[-1] == 100


def test_denoise_frames_skip_existing(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    (tmp_path / "render.1002.exr").touch()  # frame 1002 already denoised
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1003")
    assert runner.denoise_frames("db.exe", job, skip_existing=True) == 0
    assert len(calls) == 2
    processed = [c[c.index("--frame-include") + 1] for c in calls]
    assert "1001" in processed and "1003" in processed
    assert "1002" not in processed


def test_denoise_frames_stops_on_first_failure(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    call_count = [0]
    def fake_run(argv, **k):
        call_count[0] += 1
        return 1 if call_count[0] == 2 else 0
    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1003")
    assert runner.denoise_frames("db.exe", job) == 1
    assert call_count[0] == 2  # stopped after frame 2 failed


def test_denoise_frames_fallback_when_no_frames(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    # No job.frames, no matching EXRs on disk → single-batch fallback
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path))
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 1
    assert "--frame-include" not in calls[0]


# ── parallel frames ────────────────────────────────────────────────────────────

def test_parallel_calls_run_per_frame(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1003", jobs=2)
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 3
    frame_args = {c[c.index("--frame-include") + 1] for c in calls}
    assert frame_args == {"1001", "1002", "1003"}


def test_parallel_returns_max_exit_code(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    results = {1001: 0, 1002: 2, 1003: 0}
    def fake_run(argv, **k):
        frame = int(argv[argv.index("--frame-include") + 1])
        return results[frame]
    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1003", jobs=3)
    assert runner.denoise_frames("db.exe", job) == 2


def test_parallel_progress_reaches_100(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "run", lambda argv, **k: 0)
    reported = []
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1002", jobs=2)
    runner.denoise_frames("db.exe", job, on_progress=reported.append)
    assert reported[-1] == 100


def test_parallel_crossframe_still_single_batch(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1003", crossframe=True, jobs=3)
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 1


def test_parallel_skips_existing(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    (tmp_path / "render.1002.exr").touch()
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1003", jobs=3)
    assert runner.denoise_frames("db.exe", job, skip_existing=True) == 0
    assert len(calls) == 2
    frame_args = {c[c.index("--frame-include") + 1] for c in calls}
    assert "1002" not in frame_args


def test_denoise_frames_crossframe_uses_single_batch(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    # Cross-frame mode must never split into per-frame calls — patch artifacts result.
    # Expect exactly one call covering the full range, not one call per frame.
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     frames="1001-1003", crossframe=True)
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 1  # single batch, not 3 per-frame calls
    # The range string "1001-1003" is passed through as-is (not individual integers)
    idx = calls[0].index("--frame-include")
    assert calls[0][idx + 1] == "1001-1003"
