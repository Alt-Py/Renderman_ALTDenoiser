import json, os, copy
from rman_denoiser.core import config
from rman_denoiser.core.job import DenoiseJob
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_dr_config.json")

def test_build_dryrun_argv_single():
    job = DenoiseJob(inputs=["a.exr"], output_dir="/out")
    argv = config.build_dryrun_argv("denoise_batch.exe", job)
    assert argv[:2] == ["denoise_batch.exe", "-dr"]
    assert "-o" in argv and "/out" in argv and "a.exr" in argv
    assert "-cf" not in argv and "-f" not in argv

def test_build_dryrun_argv_crossframe_flow():
    job = DenoiseJob(inputs=["a.####.exr", "1-3"], output_dir="/out", crossframe=True, flow=True)
    argv = config.build_dryrun_argv("denoise_batch.exe", job)
    assert "-cf" in argv and "-f" in argv
    assert argv[-2:] == ["a.####.exr", "1-3"]

def test_aovs_from_config_lists_write_layers():
    cfg = json.load(open(FIX))
    aovs = config.aovs_from_config(cfg)
    assert "Ci" in aovs and "L_sun" in aovs and "diffuse" in aovs
    assert len(aovs) == len(set(aovs))

def test_prune_keeps_only_selected_outputs():
    cfg = json.load(open(FIX))
    pruned = config.prune_config(copy.deepcopy(cfg), ["L_sun"])
    assert config.aovs_from_config(pruned) == ["L_sun"]
    assert pruned["settings"]

def test_prune_empty_keeps_all():
    cfg = json.load(open(FIX))
    before = config.aovs_from_config(cfg)
    assert config.aovs_from_config(config.prune_config(cfg, [])) == before

def test_write_pruned_roundtrips(tmp_path):
    cfg = {"settings": {}, "passes": []}
    p = config.write_pruned(cfg, str(tmp_path / "c.json"))
    assert json.load(open(p)) == cfg
