"""Generate, parse and prune denoise_batch JSON configs."""
from __future__ import annotations
import json
import os
import subprocess
from .job import DenoiseJob


def build_dryrun_argv(exe: str, job: DenoiseJob) -> list[str]:
    argv = [exe, "-dr", "-o", job.output_dir]
    if job.crossframe:
        argv.append("-cf")
    if job.flow:
        argv.append("-f")
    argv.extend(job.inputs)
    return argv


def generate_config(exe: str, job: DenoiseJob, runner=subprocess.run) -> str:
    """Run denoise_batch -dr; return path to the written config.json."""
    os.makedirs(job.output_dir, exist_ok=True)
    result = runner(build_dryrun_argv(exe, job), check=True,
                    capture_output=True, text=True)
    path = os.path.join(job.output_dir, "config.json")
    if os.path.isfile(path):
        return path
    jsons = [f for f in os.listdir(job.output_dir) if f.endswith(".json")]
    if jsons:
        return os.path.join(job.output_dir, sorted(jsons)[0])
    # denoise_batch can fail (e.g. "No OpenEXR files found") yet exit 0, so surface
    # its own last message instead of a generic error.
    lines = ((getattr(result, "stderr", "") or "")
             + (getattr(result, "stdout", "") or "")).strip().splitlines()
    tail = lines[-1].strip() if lines else "no output from denoise_batch"
    raise RuntimeError(f"denoise_batch produced no config — {tail}")


def load_config(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def aovs_from_config(cfg: dict) -> list[str]:
    """Ordered, de-duplicated write-layers across all passes = selectable AOVs."""
    seen: dict[str, None] = {}
    for p in cfg.get("passes", []):
        for o in p.get("outputs", []):
            seen.setdefault(o["write"]["layer"], None)
    return list(seen.keys())


def prune_config(cfg: dict, selected: list[str]) -> dict:
    """Keep only outputs whose write.layer is selected; drop empty passes; keep settings.
    Empty `selected` = no change (denoise all)."""
    if not selected:
        return cfg
    keep = set(selected)
    new_passes = []
    for p in cfg.get("passes", []):
        outs = [o for o in p.get("outputs", []) if o["write"]["layer"] in keep]
        if outs:
            np = dict(p)
            np["outputs"] = outs
            new_passes.append(np)
    cfg["passes"] = new_passes
    return cfg


def write_pruned(cfg: dict, path: str) -> str:
    with open(path, "w") as fh:
        json.dump(cfg, fh, indent=2)
    return path
