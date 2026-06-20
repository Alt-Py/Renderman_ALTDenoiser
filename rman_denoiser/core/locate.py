from __future__ import annotations
import os

_DEFAULT_KNOWN = [r"C:\Program Files\Pixar\RenderManProServer-27.2"]
_EXE = "denoise_batch.exe"


def find_denoise_batch(override: str | None = None,
                       known_paths: list[str] | None = None) -> str:
    if override:
        if os.path.isfile(override):
            return override
        raise FileNotFoundError(f"denoise_batch override not found: {override}")
    candidates: list[str] = []
    rmantree = os.environ.get("RMANTREE")
    if rmantree:
        candidates.append(os.path.join(rmantree, "bin", _EXE))
    for root in (known_paths or _DEFAULT_KNOWN):
        candidates.append(os.path.join(root, "bin", _EXE))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "Could not find denoise_batch. Set $RMANTREE or pass override. "
        f"Tried: {candidates}")
