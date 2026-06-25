import pytest
from rman_denoiser.core import locate

def test_uses_override_first(tmp_path):
    exe = tmp_path / "denoise_batch.exe"; exe.write_text("")
    assert locate.find_denoise_batch(override=str(exe)) == str(exe)

def test_uses_rmantree(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"; bindir.mkdir()
    exe = bindir / "denoise_batch.exe"; exe.write_text("")
    monkeypatch.setenv("RMANTREE", str(tmp_path))
    assert locate.find_denoise_batch() == str(exe)

def test_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("RMANTREE", raising=False)
    with pytest.raises(FileNotFoundError):
        locate.find_denoise_batch(known_paths=[str(tmp_path / "nope")])
