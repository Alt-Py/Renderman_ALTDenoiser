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


# ── plan_chunks ─────────────────────────────────────────────────────────────────

def test_plan_chunks_even_split():
    chunks = runner.plan_chunks(list(range(1001, 1041)), 20, overlap=2)
    assert len(chunks) == 2
    assert chunks[0][0] == list(range(1001, 1021))        # write
    assert chunks[0][1] == list(range(1001, 1023))        # window: +2 ahead, clamped at start
    assert chunks[1][0] == list(range(1021, 1041))
    assert chunks[1][1] == list(range(1019, 1041))        # window: +2 behind, clamped at end


def test_plan_chunks_short_last():
    chunks = runner.plan_chunks(list(range(1, 26)), 10, overlap=2)
    assert [len(w) for w, _ in chunks] == [10, 10, 5]


def test_plan_chunks_size_ge_len():
    chunks = runner.plan_chunks([1, 2, 3], 50, overlap=2)
    assert chunks == [([1, 2, 3], [1, 2, 3])]


def test_plan_chunks_empty():
    assert runner.plan_chunks([], 10) == []


def test_plan_chunks_gappy_uses_index_overlap():
    chunks = runner.plan_chunks([1, 2, 3, 10, 11, 12], 2, overlap=1)
    assert chunks[0] == ([1, 2], [1, 2, 3])
    assert chunks[1] == ([3, 10], [2, 3, 10, 11])
    assert chunks[2] == ([11, 12], [10, 11, 12])


# ── source_files_for_frames ─────────────────────────────────────────────────────

def test_source_files_for_frames_maps(tmp_path):
    for n in (1001, 1002, 1003):
        (tmp_path / f"render.{n}.exr").touch()
    out = runner.source_files_for_frames(str(tmp_path / "*.exr"), [1001, 1003])
    assert out == [str(tmp_path / "render.1001.exr"), str(tmp_path / "render.1003.exr")]


def test_source_files_for_frames_skips_missing(tmp_path):
    (tmp_path / "render.1001.exr").touch()
    out = runner.source_files_for_frames(str(tmp_path / "*.exr"), [1001, 1099])
    assert out == [str(tmp_path / "render.1001.exr")]


def test_source_files_for_frames_ignores_non_frame(tmp_path):
    (tmp_path / "beauty.exr").touch()
    (tmp_path / "render.1001.exr").touch()
    out = runner.source_files_for_frames(str(tmp_path / "*.exr"), [1001])
    assert out == [str(tmp_path / "render.1001.exr")]


# ── Canceller ───────────────────────────────────────────────────────────────────

class _CancelProc:
    """Fake Popen for cancellation tests."""
    def __init__(self, lines=(), code=0):
        self.stdout = iter(lines)
        self._code = code
        self._alive = True
        self.terminated = False
    def poll(self):
        return None if self._alive else self._code
    def terminate(self):
        self.terminated = True
        self._alive = False
    def wait(self):
        return self._code


def test_canceller_not_cancelled_initially():
    assert runner.Canceller().cancelled is False


def test_canceller_cancel_terminates_registered_procs():
    c = runner.Canceller()
    p1, p2 = _CancelProc(), _CancelProc()
    c.set_proc(p1); c.set_proc(p2)
    c.cancel()
    assert c.cancelled and p1.terminated and p2.terminated


def test_canceller_set_proc_after_cancel_terminates_immediately():
    c = runner.Canceller()
    c.cancel()
    p = _CancelProc()
    c.set_proc(p)
    assert p.terminated


def test_run_registers_and_clears_proc(monkeypatch):
    proc = _CancelProc(lines=["10%\n", "100%\n"])
    monkeypatch.setattr(runner.subprocess, "Popen", lambda argv, **kw: proc)
    c = runner.Canceller()
    assert runner.run(["db.exe"], canceller=c) == 0
    assert proc not in c._procs   # cleared after completion


# ── cancellation in denoise_frames ──────────────────────────────────────────────

def test_delete_outputs_removes_matching(tmp_path):
    (tmp_path / "beauty.1005.exr").touch()
    (tmp_path / "beauty.1006.exr").touch()
    runner._delete_outputs(str(tmp_path), [1005])
    assert not (tmp_path / "beauty.1005.exr").exists()
    assert (tmp_path / "beauty.1006.exr").exists()


def test_denoise_frames_cancel_stops_sequential(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    c = runner.Canceller()
    calls = []
    def fake_run(argv, **k):
        calls.append(argv)
        c.cancel()                      # user hits Stop during the first frame
        return runner.CANCELLED
    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1003")
    assert runner.denoise_frames("db.exe", job, canceller=c) == runner.CANCELLED
    assert len(calls) == 1              # did not continue to later frames


def test_denoise_frames_cancel_discards_interrupted_frame(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    (tmp_path / "render.1001.exr").touch()   # partial output from the interrupted frame
    c = runner.Canceller()
    def fake_run(argv, **k):
        c.cancel()
        return runner.CANCELLED
    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path), frames="1001-1003")
    runner.denoise_frames("db.exe", job, canceller=c, skip_existing=False)
    assert not (tmp_path / "render.1001.exr").exists()


# ── chunked cross-frame ─────────────────────────────────────────────────────────

def _make_frames(directory, lo, hi):
    directory.mkdir(parents=True, exist_ok=True)
    for n in range(lo, hi + 1):
        (directory / f"render.{n}.exr").touch()
    return str(directory / "*.exr")


def _gen_into(out):
    def _gen(exe, job, **k):
        (out / "config.json").write_text('{"settings": {}, "passes": []}')
        return str(out / "config.json")
    return _gen


def test_chunked_runs_one_batch_per_chunk(monkeypatch, tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    out.mkdir()
    pattern = _make_frames(src, 1001, 1040)
    seen_inputs = []
    def fake_gen(exe, job, **k):
        seen_inputs.append(list(job.inputs))
        (out / "config.json").write_text('{"settings": {}, "passes": []}')
        return str(out / "config.json")
    monkeypatch.setattr(runner._config, "generate_config", fake_gen)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=[pattern], output_dir=str(out),
                     crossframe=True, chunk_size=20, frames="1001-1040")
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 2
    includes = [c[c.index("--frame-include") + 1] for c in calls]
    assert includes == ["1001-1020", "1021-1040"]
    assert [len(x) for x in seen_inputs] == [22, 22]   # window = 20 + 2 overlap, clamped


def test_chunked_falls_back_when_range_fits_one_chunk(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=["a.exr"], output_dir=str(tmp_path),
                     crossframe=True, chunk_size=50, frames="1001-1010")
    assert runner.denoise_frames("db.exe", job) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--frame-include") + 1] == "1001-1010"


def test_chunked_skips_fully_existing_chunk(monkeypatch, tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    out.mkdir()
    pattern = _make_frames(src, 1001, 1040)
    monkeypatch.setattr(runner._config, "generate_config", _gen_into(out))
    for n in range(1001, 1021):                      # chunk 0 already denoised
        (out / f"out.{n}.exr").touch()
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or 0)
    job = DenoiseJob(inputs=[pattern], output_dir=str(out),
                     crossframe=True, chunk_size=20, frames="1001-1040")
    assert runner.denoise_frames("db.exe", job, skip_existing=True) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--frame-include") + 1] == "1021-1040"


def test_chunked_cancel_discards_chunk(monkeypatch, tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    out.mkdir()
    pattern = _make_frames(src, 1001, 1040)
    monkeypatch.setattr(runner._config, "generate_config", _gen_into(out))
    (out / "out.1001.exr").touch()                   # partial output of interrupted chunk
    c = runner.Canceller()
    def fake_run(argv, **k):
        c.cancel()
        return runner.CANCELLED
    monkeypatch.setattr(runner, "run", fake_run)
    job = DenoiseJob(inputs=[pattern], output_dir=str(out),
                     crossframe=True, chunk_size=20, frames="1001-1040")
    assert runner.denoise_frames("db.exe", job, canceller=c, skip_existing=False) == runner.CANCELLED
    assert not (out / "out.1001.exr").exists()
