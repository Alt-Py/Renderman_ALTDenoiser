"""Command-line front-end for the RenderMan denoiser wrapper."""
from __future__ import annotations
import argparse
import os
import sys
from .core.job import DenoiseJob, expand_input
from .core import locate, config, runner

_expand_input = expand_input  # backward-compatible alias


def parse_args(argv: list[str]):
    p = argparse.ArgumentParser(
        prog="rman-denoise",
        description="Wrapper around RenderMan denoise_batch with AOV selection.")
    p.add_argument("input", help="folder, glob, or name.####.exr pattern")
    p.add_argument("--aovs", default="",
                   help="comma-separated AOVs to denoise (default: all)")
    p.add_argument("--list-aovs", action="store_true",
                   help="print discovered AOVs and exit")
    p.add_argument("--crossframe", action="store_true", help="cross-frame denoising")
    p.add_argument("--single", dest="crossframe", action="store_false",
                   help="single-frame denoising (default)")
    p.set_defaults(crossframe=False)
    p.add_argument("--flow", action="store_true", help="compute optical flow")
    p.add_argument("--frames", default=None, help="frame-include list, e.g. 1001-1008,1012")
    p.add_argument("--tiles", type=int, default=None, help="square tile size for low RAM")
    p.add_argument("--low-ram", action="store_true", help="process AOVs sequentially")
    p.add_argument("--asymmetry", type=float, default=0.0)
    p.add_argument("--output", default=None, help="output dir (default: <input>/denoised)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the denoise_batch command, do not run")
    p.add_argument("--jobs", type=int, default=1,
                   help="parallel frame workers 1-4 (default: 1). Ignored for --crossframe.")
    p.add_argument("--rman", default=None, help="override denoise_batch path")
    a = p.parse_args(argv)

    base = a.input.rstrip("/\\")
    default_parent = base if os.path.isdir(base) else os.path.dirname(base)
    out = a.output or os.path.join(default_parent, "denoised")
    jobs = max(1, min(a.jobs, 4))
    job = DenoiseJob(
        inputs=_expand_input(a.input),
        output_dir=out,
        selected_aovs=[s for s in a.aovs.split(",") if s],
        crossframe=a.crossframe, flow=a.flow, frames=a.frames,
        tiles=a.tiles, low_ram=a.low_ram, asymmetry=a.asymmetry,
        denoise_batch=a.rman, jobs=jobs,
    )
    return job, a


def main(argv: list[str] | None = None) -> int:
    job, a = parse_args(sys.argv[1:] if argv is None else argv)
    exe = locate.find_denoise_batch(override=job.denoise_batch)
    if a.list_aovs:
        cfg = config.load_config(config.generate_config(exe, job))
        print("\n".join(config.aovs_from_config(cfg)))
        return 0
    if a.dry_run:
        print(" ".join(config.build_dryrun_argv(exe, job)))
        return 0
    return runner.denoise_frames(exe, job,
                                 on_progress=lambda pct: print(f"{pct}%"),
                                 on_log=lambda line: print(line))


if __name__ == "__main__":
    raise SystemExit(main())
