"""Pure view-model for the GUI (no Qt imports) — holds state, validates, builds a job."""
from __future__ import annotations
from dataclasses import dataclass, field
from .core.job import DenoiseJob, expand_input


@dataclass
class GuiModel:
    input_path: str = ""
    available_aovs: list[str] = field(default_factory=list)
    selected_aovs: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    crossframe: bool = False
    flow: bool = False
    frames: str | None = None
    tiles: int | None = None
    jobs: int = 1

    def set_input(self, path: str) -> None:
        self.input_path = path

    def set_available_aovs(self, aovs: list[str]) -> None:
        self.available_aovs = list(aovs)
        self.selected_aovs = list(aovs)  # default: all on

    def set_missing_required(self, missing: list[str]) -> None:
        self.missing_required = list(missing)

    def select(self, aovs: list[str]) -> None:
        self.selected_aovs = [a for a in aovs if a in self.available_aovs]

    def can_run(self) -> tuple[bool, str]:
        if not self.input_path:
            return False, "Choose an input render first."
        if self.missing_required:
            return False, ("Render is missing required denoise channels: "
                           + ", ".join(self.missing_required)
                           + " — enable denoise / EXR Legacy Mode in render settings.")
        return True, ""

    def to_job(self, output_dir: str) -> DenoiseJob:
        # All AOVs selected == denoise everything == empty selection.
        sel = [] if self.selected_aovs == self.available_aovs else list(self.selected_aovs)
        return DenoiseJob(
            inputs=expand_input(self.input_path), output_dir=output_dir,
            selected_aovs=sel, crossframe=self.crossframe, flow=self.flow,
            frames=self.frames, tiles=self.tiles, jobs=self.jobs,
        )
