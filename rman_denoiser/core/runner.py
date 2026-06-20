"""Build and execute the denoise_batch run command."""
from __future__ import annotations
import glob as _glob
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from .job import DenoiseJob
from . import config as _config


# ── regex for progress lines emitted by denoise_batch -p ──────────────────────
_PCT = re.compile(r"^\s*(\d{1,3})%\s*$")

CANCELLED = 130  # sentinel exit code for a user-cancelled run


class Canceller:
    """Cooperative cancellation plus handles to the live subprocess(es)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._procs: set = set()
        self._lock = threading.Lock()

    def set_proc(self, proc) -> None:
        with self._lock:
            self._procs.add(proc)
            cancelled = self._event.is_set()
        if cancelled and proc.poll() is None:
            proc.terminate()

    def clear_proc(self, proc) -> None:
        with self._lock:
            self._procs.discard(proc)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            if p.poll() is None:
                p.terminate()


def parse_frame_range(frames_str: str) -> list[int]:
    """Parse "1001-1003,1005" into [1001, 1002, 1003, 1005]."""
    try:
        result: set[int] = set()
        for part in frames_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                result.update(range(int(start), int(end) + 1))
            else:
                result.add(int(part))
        return sorted(result)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Bad frame spec {frames_str!r}: {exc}") from exc


def frames_from_glob(pattern: str) -> list[int]:
    """Glob *pattern* on disk and return sorted frame numbers.

    Handles ``name.####.exr`` (RenderMan 4-digit frame pattern) and ``dir/*.exr``
    (expanded directory). Frame number = digit run immediately before ``.exr``.
    Returns [] when nothing matches or no filename has a frame number.
    """
    if "####" in pattern:
        disk_pattern = pattern.replace("####", "[0-9][0-9][0-9][0-9]")
    else:
        disk_pattern = pattern
    matches = _glob.glob(disk_pattern)
    frames: list[int] = []
    _frame_re = re.compile(r"\.(\d+)\.exr$", re.IGNORECASE)

    for path in matches:
        m = _frame_re.search(path)
        if m:
            frames.append(int(m.group(1)))
    return sorted(frames)


def plan_chunks(frames: list[int], chunk_size: int,
                overlap: int = 2) -> list[tuple[list[int], list[int]]]:
    """Split sorted *frames* into consecutive blocks of *chunk_size*.

    Returns [(write_frames, window_frames), ...]:
      write_frames  = the block's own frames (denoised + written once),
      window_frames = write_frames plus up to *overlap* neighbours on each side
                      (from the sorted list, clamped to its ends) for temporal context.
    """
    frames = sorted(frames)
    n = len(frames)
    if not frames:
        return []
    if chunk_size <= 0:
        return [(list(frames), list(frames))]
    chunks: list[tuple[list[int], list[int]]] = []
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        write = frames[start:end]
        window = frames[max(0, start - overlap):min(n, end + overlap)]
        chunks.append((write, window))
    return chunks


def source_files_for_frames(pattern: str, frames: list[int]) -> list[str]:
    """Glob *pattern* on disk; return the source EXRs for *frames* (sorted,
    missing frames skipped). Frame number = digit run immediately before ``.exr``."""
    disk_pattern = pattern.replace("####", "[0-9][0-9][0-9][0-9]") if "####" in pattern else pattern
    frame_re = re.compile(r"\.(\d+)\.exr$", re.IGNORECASE)
    by_frame: dict[int, str] = {}
    for path in _glob.glob(disk_pattern):
        m = frame_re.search(path)
        if m:
            by_frame[int(m.group(1))] = path
    return [by_frame[f] for f in sorted(frames) if f in by_frame]


def _build_base_argv(exe: str, config_path: str, job: DenoiseJob) -> list[str]:
    """Argv for denoise_batch without a --frame-include override."""
    argv = [exe, "-j", config_path, "-p"]
    if job.tiles:
        argv += ["--tiles", str(job.tiles), str(job.tiles)]
    return argv


def build_run_argv(exe: str, config_path: str, job: DenoiseJob) -> list[str]:
    """Return the argv list to invoke denoise_batch from a JSON config."""
    argv = _build_base_argv(exe, config_path, job)
    if job.frames:
        argv += ["--frame-include", job.frames]
    return argv


def run(argv: list[str], on_progress=None, on_log=None, canceller=None) -> int:
    """Run denoise_batch, stream stdout, call on_progress(int 0-100).

    Returns the process exit code.
    Lines matching ``<digits>%`` are forwarded to *on_progress*; all other
    lines go to *on_log* (both callbacks are optional). If *canceller* is given,
    the process is registered so a concurrent ``canceller.cancel()`` can
    terminate it.
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if canceller is not None:
        canceller.set_proc(proc)
    try:
        for line in proc.stdout:
            m = _PCT.match(line)
            if m and on_progress:
                on_progress(int(m.group(1)))
            elif on_log:
                on_log(line.rstrip("\n"))
        return proc.wait()
    finally:
        if canceller is not None:
            canceller.clear_proc(proc)


def _delete_outputs(output_dir: str, frames: list[int]) -> None:
    """Remove denoised EXRs for *frames* in *output_dir* (discard-on-stop)."""
    for f in frames:
        for path in _glob.glob(os.path.join(output_dir, f"*.{f:04d}.exr")):
            try:
                os.remove(path)
            except OSError:
                pass


def denoise(exe: str, job: DenoiseJob, on_progress=None, on_log=None) -> int:
    """Full orchestration: generate config → prune AOVs → run denoise_batch.

    Returns the process exit code.
    """
    cfg_path = _config.generate_config(exe, job)
    cfg = _config.load_config(cfg_path)
    cfg = _config.prune_config(cfg, job.selected_aovs)
    pruned = os.path.join(job.output_dir, "rmandenoise_pruned.json")
    _config.write_pruned(cfg, pruned)
    argv = build_run_argv(exe, pruned, job)
    return run(argv, on_progress=on_progress, on_log=on_log)


def _run_frames_parallel(
    exe: str,
    pruned: str,
    job: DenoiseJob,
    frame_list: list[int],
    workers: int,
    on_progress,
    on_log,
    skip_existing: bool,
    canceller=None,
) -> int:
    total = len(frame_list)
    frame_pct: dict[int, int] = {}
    lock = threading.Lock()
    base_argv = _build_base_argv(exe, pruned, job)

    def _emit():
        if on_progress:
            on_progress(int(sum(frame_pct.values()) / total))

    def _work(frame: int) -> int:
        if canceller is not None and canceller.cancelled:
            return CANCELLED
        if skip_existing:
            existing = _glob.glob(os.path.join(job.output_dir, f"*.{frame:04d}.exr"))
            if existing:
                if on_log:
                    on_log(f"skip frame {frame} (exists)")
                with lock:
                    frame_pct[frame] = 100
                    _emit()
                return 0

        argv = base_argv + ["--frame-include", str(frame)]

        def _prog(p: int):
            with lock:
                frame_pct[frame] = p
                _emit()

        def _log(line: str):
            if on_log:
                on_log(f"[{frame}] {line}")

        code = run(argv, on_progress=_prog, on_log=_log, canceller=canceller)
        if canceller is not None and canceller.cancelled:
            _delete_outputs(job.output_dir, [frame])
            return CANCELLED
        return code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_work, f) for f in frame_list]
        codes = [f.result() for f in futures]

    if canceller is not None and canceller.cancelled:
        return CANCELLED
    if on_progress:
        on_progress(100)
    return max(codes) if codes else 0


def _run_crossframe_chunked(exe: str, job: DenoiseJob, on_progress=None,
                            on_log=None, canceller=None, skip_existing: bool = True) -> int:
    """Cross-frame denoise in fixed-size chunks: one fresh denoise_batch per chunk,
    each handed only its window's input EXRs, so peak RAM is bounded by one chunk."""
    if job.frames:
        frames = parse_frame_range(job.frames)
    else:
        frames = frames_from_glob(job.inputs[0] if job.inputs else "")
    chunks = plan_chunks(frames, job.chunk_size)
    total = len(chunks)
    pruned = os.path.join(job.output_dir, "rmandenoise_pruned.json")

    for i, (write_frames, window_frames) in enumerate(chunks):
        if canceller is not None and canceller.cancelled:
            return CANCELLED

        if skip_existing and all(
            _glob.glob(os.path.join(job.output_dir, f"*.{f:04d}.exr")) for f in write_frames
        ):
            if on_log:
                on_log(f"skip chunk {write_frames[0]}-{write_frames[-1]} (exists)")
            if on_progress:
                on_progress(int((i + 1) / total * 100))
            continue

        window_files = source_files_for_frames(job.inputs[0] if job.inputs else "", window_frames)
        sub = replace(job, inputs=window_files, frames=None, chunk_size=0)
        cfg = _config.prune_config(_config.load_config(_config.generate_config(exe, sub)),
                                   sub.selected_aovs)
        _config.write_pruned(cfg, pruned)

        include = f"{write_frames[0]}-{write_frames[-1]}"
        argv = _build_base_argv(exe, pruned, sub) + ["--frame-include", include]
        if on_log:
            on_log(f"chunk {include}  ({len(window_files)} input frames)")

        code = run(argv, on_log=on_log, canceller=canceller)
        if canceller is not None and canceller.cancelled:
            _delete_outputs(job.output_dir, write_frames)
            return CANCELLED
        if on_progress:
            on_progress(int((i + 1) / total * 100))
        if code != 0:
            return code

    if on_progress:
        on_progress(100)
    return 0


def denoise_frames(
    exe: str,
    job: DenoiseJob,
    on_progress=None,
    on_log=None,
    skip_existing: bool = True,
    canceller=None,
) -> int:
    """Per-frame orchestration: generate config once, run denoise_batch per frame.

    Each denoised EXR is written to disk as soon as its frame finishes.
    Falls back to a single denoise_batch call when:
    - cross-frame mode is active (temporal filtering requires all frames in one pass)
    - no frame list can be determined (e.g. input is a single EXR with no frame number)
    """
    # Chunked cross-frame: each chunk builds its own (smaller) config, so skip the
    # top-level config generation and delegate before loading the full range.
    if job.crossframe and job.chunk_size:
        if job.frames:
            _frames = parse_frame_range(job.frames)
        else:
            _frames = frames_from_glob(job.inputs[0] if job.inputs else "")
        if _frames and len(_frames) > job.chunk_size:
            return _run_crossframe_chunked(exe, job, on_progress, on_log,
                                           canceller, skip_existing)

    cfg_path = _config.generate_config(exe, job)
    cfg = _config.load_config(cfg_path)
    cfg = _config.prune_config(cfg, job.selected_aovs)
    pruned = os.path.join(job.output_dir, "rmandenoise_pruned.json")
    _config.write_pruned(cfg, pruned)

    # Cross-frame denoising processes all frames in one temporal pass — splitting
    # into per-frame calls breaks the temporal filtering and produces patch artifacts.
    if job.crossframe:
        if on_log:
            on_log("Cross-frame mode: running as single batch")
        return run(build_run_argv(exe, pruned, job),
                   on_progress=on_progress, on_log=on_log, canceller=canceller)

    if job.frames:
        frames = parse_frame_range(job.frames)
    else:
        pattern = job.inputs[0] if job.inputs else ""
        frames = frames_from_glob(pattern)

    # Base argv without --frame-include so we can append per-frame
    base_argv = _build_base_argv(exe, pruned, job)

    if not frames:
        if on_log:
            on_log("No frame range found — running as single batch")
        return run(base_argv, on_progress=on_progress, on_log=on_log, canceller=canceller)

    workers = max(1, min(job.jobs or 1, len(frames)))
    if workers > 1:
        return _run_frames_parallel(exe, pruned, job, frames, workers,
                                    on_progress, on_log, skip_existing, canceller)

    n = len(frames)
    for i, frame in enumerate(frames):
        if canceller is not None and canceller.cancelled:
            return CANCELLED
        if skip_existing:
            existing = _glob.glob(os.path.join(job.output_dir, f"*.{frame:04d}.exr"))
            if existing:
                if on_log:
                    on_log(f"skip frame {frame} (exists)")
                if on_progress:
                    on_progress(int((i + 1) / n * 100))
                continue

        argv = base_argv + ["--frame-include", str(frame)]
        scale = 1 / n
        offset = i / n

        def _scaled_progress(p, _off=offset, _sc=scale):
            if on_progress:
                on_progress(int((_off + p / 100 * _sc) * 100))

        code = run(argv, on_progress=_scaled_progress, on_log=on_log, canceller=canceller)
        if canceller is not None and canceller.cancelled:
            _delete_outputs(job.output_dir, [frame])
            return CANCELLED
        if on_progress:
            on_progress(int((i + 1) / n * 100))
        if code != 0:
            return code

    return 0
