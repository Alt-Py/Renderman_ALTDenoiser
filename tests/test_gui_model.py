from rman_denoiser.gui_model import GuiModel


def test_toggle_and_job():
    m = GuiModel()
    m.set_input("render/")
    m.set_available_aovs(["Ci", "diffuse", "specular"])
    m.select(["diffuse"])
    m.crossframe = True
    m.flow = True
    job = m.to_job(output_dir="/out")
    assert job.selected_aovs == ["diffuse"]
    assert job.crossframe and job.flow
    assert job.inputs == ["render/"]


def test_validation_blocks_run_without_input():
    m = GuiModel()
    ok, msg = m.can_run()
    assert not ok and "input" in msg.lower()


def test_validation_reports_missing_required():
    m = GuiModel()
    m.set_input("render/")
    m.set_missing_required(["sampleCount"])
    ok, msg = m.can_run()
    assert not ok and "sampleCount" in msg


def test_all_selected_means_denoise_all():
    m = GuiModel()
    m.set_input("r/")
    m.set_available_aovs(["a", "b"])  # set_available defaults to all selected
    job = m.to_job("/out")
    assert job.selected_aovs == []  # all -> empty -> denoise everything


def test_select_ignores_unknown_aovs():
    m = GuiModel()
    m.set_available_aovs(["a", "b"])
    m.select(["a", "zzz"])
    assert m.selected_aovs == ["a"]


def test_to_job_passes_jobs():
    m = GuiModel(input_path="/tmp/foo")
    m.jobs = 3
    job = m.to_job("/tmp/out")
    assert job.jobs == 3


def test_to_job_expands_directory_input(tmp_path):
    m = GuiModel()
    m.set_input(str(tmp_path))            # a real directory
    m.set_available_aovs(["L_sun", "diffuse"])
    m.select(["L_sun"])                   # subset -> kept as selection
    job = m.to_job(str(tmp_path / "denoised"))
    assert job.inputs == [str(tmp_path / "*.exr")]
    assert job.selected_aovs == ["L_sun"]
