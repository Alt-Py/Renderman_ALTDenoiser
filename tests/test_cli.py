from rman_denoiser import cli
from rman_denoiser.core.job import DenoiseJob


def test_parse_basic():
    job, a = cli.parse_args(["render.####.exr", "--aovs", "diffuse,specular",
                             "--crossframe", "--flow", "--tiles", "1024",
                             "--frames", "1-3", "--output", "/out"])
    assert isinstance(job, DenoiseJob)
    assert job.selected_aovs == ["diffuse", "specular"]
    assert job.crossframe and job.flow
    assert job.tiles == 1024 and job.frames == "1-3"
    assert job.output_dir == "/out"
    assert job.inputs == ["render.####.exr"]


def test_default_output_and_all_aovs():
    job, a = cli.parse_args(["render.####.exr"])
    assert job.output_dir.endswith("denoised")
    assert job.selected_aovs == []  # empty = denoise all


def test_directory_input_expands_to_glob(tmp_path):
    d = tmp_path / "beauty"
    d.mkdir()
    job, a = cli.parse_args([str(d)])
    assert job.inputs == [str(d / "*.exr")]


def test_dry_run_prints_command(capsys, monkeypatch):
    from rman_denoiser.core import locate
    monkeypatch.setattr(locate, "find_denoise_batch", lambda override=None: "denoise_batch.exe")
    rc = cli.main(["render.####.exr", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "denoise_batch.exe" in out and "-dr" in out


def test_list_aovs_prints_discovered(capsys, monkeypatch):
    from rman_denoiser.core import locate, config
    monkeypatch.setattr(locate, "find_denoise_batch", lambda override=None: "denoise_batch.exe")
    monkeypatch.setattr(config, "generate_config", lambda exe, job, **k: "cfg.json")
    monkeypatch.setattr(config, "load_config", lambda p: {"passes": [
        {"outputs": [{"write": {"layer": "L_sun"}}, {"write": {"layer": "diffuse"}}]}]})
    rc = cli.main(["render.####.exr", "--list-aovs"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "L_sun" in out and "diffuse" in out
