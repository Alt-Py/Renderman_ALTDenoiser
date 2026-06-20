from __future__ import annotations
import os
from dataclasses import dataclass, field


def expand_input(inp: str) -> list[str]:
    """A bare directory becomes a `<dir>/*.exr` glob; otherwise pass through.

    denoise_batch needs a file / glob / `name.####.exr` pattern — a bare folder
    yields "No OpenEXR files found" (and exits 0), so always expand directories.
    """
    if os.path.isdir(inp):
        return [os.path.join(inp, "*.exr")]
    return [inp]


@dataclass
class DenoiseJob:
    inputs: list[str]
    output_dir: str
    selected_aovs: list[str] = field(default_factory=list)  # empty = all
    crossframe: bool = False
    flow: bool = False
    frames: str | None = None
    tiles: int | None = None
    low_ram: bool = False
    asymmetry: float = 0.0
    denoise_batch: str | None = None
    jobs: int = 1
