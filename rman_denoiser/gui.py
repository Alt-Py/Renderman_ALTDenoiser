"""Standalone PySide GUI for the RenderMan denoiser — Alternatives Productions style.

Launch via RMDenoise.bat (Houdini's hython, PySide2). Falls back to PySide6.
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading

try:
    from PySide2 import QtWidgets, QtCore, QtGui, QtSvg
    _EXEC = "exec_"
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui, QtSvg
    _EXEC = "exec"

from .core import locate, config, runner
from .core.job import DenoiseJob, expand_input
from .gui_model import GuiModel

def _detect_houdini() -> bool:
    """True only inside an *interactive* Houdini UI session (not standalone hython).

    hython (used by RMDenoise.bat) also pre-creates a QApplication and can import
    ``hou``, so neither of those distinguishes "embedded in Houdini's UI" from our
    own standalone launcher. ``hou.isUIAvailable()`` is True only when Houdini's
    interactive UI — and its Qt event loop — is actually running.
    """
    try:
        import hou
    except ImportError:
        return False
    try:
        return bool(hou.isUIAvailable())
    except Exception:
        return False

_IN_HOUDINI = _detect_houdini()

C = {
    "deep": "#04050A", "bg": "#0B0E15", "bg2": "#11151F",
    "ink": "#EDEDEA", "mute": "#8A8A86", "faint": "#5C5C58",
    "red": "#E0252C", "red_hi": "#F0343B", "blue": "#2D5BFF",
    "hair": "rgba(237,237,234,0.10)", "hairS": "rgba(237,237,234,0.18)",
}

QSS = f"""
QWidget {{ background:{C['bg']}; color:{C['ink']}; font-family:'Satoshi','Segoe UI',sans-serif; font-size:13px; }}
QLineEdit, QComboBox, QListWidget {{ background:{C['deep']}; border:1px solid {C['hair']}; border-radius:8px; padding:7px 9px; }}
QListWidget::item {{ padding:5px 2px; }}
QListWidget::item:selected {{ background:transparent; color:{C['ink']}; }}
QPushButton#browse {{ background:{C['bg2']}; border:1px solid {C['hairS']}; border-radius:8px; padding:8px 14px; color:{C['ink']}; }}
QPushButton#browse:hover {{ background:#171c28; }}
QPushButton#go {{ background:{C['red']}; color:#FFFFFF; border:none; border-radius:10px; padding:14px; font-weight:700; letter-spacing:3px; }}
QPushButton#go:hover {{ background:{C['red_hi']}; }}
QPushButton#go:disabled {{ background:{C['bg2']}; color:{C['faint']}; }}
QProgressBar {{ background:{C['bg2']}; border:none; border-radius:3px; max-height:6px; }}
QProgressBar::chunk {{ background:{C['blue']}; border-radius:3px; }}
QCheckBox::indicator {{ width:15px; height:15px; border-radius:4px; border:1px solid {C['hairS']}; background:{C['deep']}; }}
QCheckBox::indicator:checked {{ background:{C['red']}; border-color:{C['red']}; }}
QComboBox::drop-down {{ border:none; }}
"""


def _eyebrow(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text.upper())
    lbl.setStyleSheet(f"font-family:'Orbitron','Segoe UI'; color:{C['mute']}; "
                      f"font-size:10px; letter-spacing:3px;")
    return lbl


def _logo_label(height: int = 38) -> QtWidgets.QLabel:
    path = os.path.join(os.path.dirname(__file__), "assets", "Logo_v07.svg")
    lbl = QtWidgets.QLabel()
    renderer = QtSvg.QSvgRenderer(path)
    size = renderer.defaultSize()
    w = int(size.width() / size.height() * height) if size.height() else height
    pm = QtGui.QPixmap(w, height)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    renderer.render(painter)
    painter.end()
    lbl.setPixmap(pm)
    return lbl


class ConsoleWindow(QtWidgets.QWidget):
    """Detached, unstyled output console — opened automatically on run start."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Denoiser Output")
        self.resize(700, 400)
        layout = QtWidgets.QVBoxLayout(self)

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(self._text)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        clear = QtWidgets.QPushButton("Clear")
        clear.clicked.connect(self._text.clear)
        copy = QtWidgets.QPushButton("Copy All")
        copy.clicked.connect(self._copy_all)
        btn_row.addWidget(clear)
        btn_row.addWidget(copy)
        layout.addLayout(btn_row)

    def append(self, line: str) -> None:
        self._text.appendPlainText(line)
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_all(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self._text.toPlainText())

    def clear(self) -> None:
        self._text.clear()


class MainWindow(QtWidgets.QWidget):
    sig_aovs = QtCore.Signal(list)
    sig_progress = QtCore.Signal(int)
    sig_log = QtCore.Signal(str)
    sig_done = QtCore.Signal(int)
    sig_error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.model = GuiModel()
        self.setWindowTitle("RenderMan Denoiser — The Protocol")
        self.setMinimumWidth(560)
        self.setStyleSheet(QSS)
        self._build()
        self._console = ConsoleWindow()
        self.sig_aovs.connect(self._populate_aovs)
        self.sig_progress.connect(self.bar.setValue)
        self.sig_log.connect(self._console.append)
        self.sig_done.connect(self._on_done)
        self.sig_error.connect(self._on_error)

    def _build(self):
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(15)
        header.addWidget(_logo_label(38))
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(7)
        titles.addWidget(_eyebrow("The Protocol"))
        t = QtWidgets.QLabel("RenderMan Denoiser")
        t.setStyleSheet(f"font-weight:700; font-size:16px; color:{C['ink']};")
        titles.addWidget(t)
        header.addLayout(titles)
        header.addStretch(1)
        v.addLayout(header)
        v.addWidget(self._hr())

        v.addWidget(_eyebrow("Render input"))
        row = QtWidgets.QHBoxLayout()
        self.input_edit = QtWidgets.QLineEdit()
        self.input_edit.setPlaceholderText("Render folder or name.####.exr")
        self.input_edit.setToolTip("Render folder containing EXRs, or a frame pattern like name.####.exr")
        self.input_edit.editingFinished.connect(self._discover)
        browse = QtWidgets.QPushButton("Browse")
        browse.setObjectName("browse")
        browse.clicked.connect(self._browse)
        row.addWidget(self.input_edit)
        row.addWidget(browse)
        v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet(f"color:{C['mute']}; font-size:12px;")
        v.addWidget(self.status)

        v.addWidget(_eyebrow("AOVs to denoise"))
        self.aov_list = QtWidgets.QListWidget()
        self.aov_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.aov_list.setMaximumHeight(170)
        self.aov_list.setToolTip("Select which AOVs to denoise. Fewer AOVs = faster and less RAM")
        v.addWidget(self.aov_list)

        v.addWidget(_eyebrow("Mode & performance"))
        opts = QtWidgets.QGridLayout()
        opts.setHorizontalSpacing(18)
        self.cf = QtWidgets.QCheckBox("Cross-frame")
        self.cf.setToolTip("Use temporal information from neighboring frames to reduce flickering")
        self.flow = QtWidgets.QCheckBox("Optical flow")
        self.flow.setToolTip("Compute motion vectors between frames for better temporal alignment. Slower but improves denoising on moving content")
        self.flow.setEnabled(False)
        self.cf.toggled.connect(self._on_cf_toggled)
        self.frames = QtWidgets.QLineEdit()
        self.frames.setPlaceholderText("all")
        self.frames.setToolTip("Frame range to process, e.g. 1001-1008. Leave empty for all frames. Already-denoised frames are skipped automatically")
        self.tiles = QtWidgets.QComboBox()
        self.tiles.addItems(["off", "512", "1024"])
        self.tiles.setToolTip("Split each frame into tiles to limit RAM usage. Slower but prevents out-of-memory on large renders or many AOVs")
        opts.addWidget(self.cf, 0, 0)
        opts.addWidget(self.flow, 0, 1)
        opts.addWidget(QtWidgets.QLabel("Frames"), 1, 0)
        opts.addWidget(self.frames, 1, 1)
        opts.addWidget(QtWidgets.QLabel("Tiles (RAM)"), 2, 0)
        opts.addWidget(self.tiles, 2, 1)

        opts.addWidget(QtWidgets.QLabel("Workers"), 3, 0)
        workers_row = QtWidgets.QHBoxLayout()
        self.workers_combo = QtWidgets.QComboBox()
        self.workers_combo.addItems(["1", "2", "3", "4"])
        self.workers_combo.setToolTip(
            "Frames processed simultaneously. 2 is safe. "
            "3–4 risk out-of-memory on complex or high-AOV renders."
        )
        self._ram_warn = QtWidgets.QLabel("⚠ RAM intensive")
        self._ram_warn.setStyleSheet(f"color:{C['red']}; font-size:11px;")
        self._ram_warn.setVisible(False)
        self.workers_combo.currentTextChanged.connect(
            lambda t: self._ram_warn.setVisible(int(t) >= 3)
        )
        workers_row.addWidget(self.workers_combo)
        workers_row.addWidget(self._ram_warn)
        workers_row.addStretch(1)
        opts.addLayout(workers_row, 3, 1)

        v.addLayout(opts)

        v.addWidget(_eyebrow("Output folder"))
        orow = QtWidgets.QHBoxLayout()
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("<input>/denoised")
        self.output_edit.setToolTip("Where to write denoised EXRs. Defaults to a 'denoised' subfolder next to the input")
        obrowse = QtWidgets.QPushButton("Browse")
        obrowse.setObjectName("browse")
        obrowse.clicked.connect(self._browse_output)
        orow.addWidget(self.output_edit)
        orow.addWidget(obrowse)
        v.addLayout(orow)

        self.go = QtWidgets.QPushButton("DENOISE")
        self.go.setObjectName("go")
        self.go.clicked.connect(self._run)
        v.addWidget(self.go)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self._show_log_btn = QtWidgets.QPushButton("Show Log")
        self._show_log_btn.setObjectName("browse")
        self._show_log_btn.clicked.connect(self._open_console)
        v.addWidget(self._show_log_btn)

        v.addWidget(self._hr())
        footer = QtWidgets.QHBoxLayout()
        if _IN_HOUDINI:
            standalone_btn = QtWidgets.QPushButton("Launch Standalone")
            standalone_btn.setObjectName("browse")
            standalone_btn.clicked.connect(self._launch_standalone)
            footer.addWidget(standalone_btn)
        credit_style = (f"font-family:'Orbitron','Segoe UI'; color:{C['faint']}; "
                        f"font-size:10px; letter-spacing:2px;")
        author = QtWidgets.QLabel("Made by Thomas Spony")
        author.setStyleSheet(credit_style)
        footer.addWidget(author)
        footer.addStretch(1)
        ver = QtWidgets.QLabel("V1.0.0 · RM 27.2")
        ver.setStyleSheet(credit_style)
        footer.addWidget(ver)
        v.addLayout(footer)

    def _hr(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:rgba(237,237,234,0.10);")
        return line

    def _on_cf_toggled(self, checked: bool) -> None:
        self.flow.setEnabled(checked)
        self.workers_combo.setEnabled(not checked)
        if checked:
            self.workers_combo.setCurrentIndex(0)

    def _open_console(self):
        self._console.show()
        self._console.raise_()
        self._console.activateWindow()

    def _launch_standalone(self):
        import subprocess
        bat = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "RMDenoise.bat"))
        subprocess.Popen([bat], shell=True)

    def closeEvent(self, event):
        self._console.close()
        super().closeEvent(event)

    # ── actions ──────────────────────────────────────────────────────────
    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose render folder")
        if d:
            self.input_edit.setText(d)
            self._discover()

    def _browse_output(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.output_edit.setText(d)

    def _default_output(self) -> str:
        ip = self.model.input_path
        base = ip if os.path.isdir(ip) else os.path.dirname(ip)
        return os.path.join(base, "denoised")

    def _discover(self):
        path = self.input_edit.text().strip()
        if not path:
            return
        self.model.set_input(path)
        self.status.setText("scanning…")
        threading.Thread(target=self._discover_worker, args=(path,), daemon=True).start()

    def _discover_worker(self, path: str):
        try:
            exe = locate.find_denoise_batch()
            job = DenoiseJob(inputs=expand_input(path), output_dir=tempfile.mkdtemp())
            cfg = config.load_config(config.generate_config(exe, job))
            self.sig_aovs.emit(config.aovs_from_config(cfg))
        except Exception as exc:  # surface, don't crash
            self.sig_error.emit(str(exc))

    def _populate_aovs(self, aovs: list):
        self.model.set_available_aovs(aovs)
        self.aov_list.clear()
        for a in aovs:
            item = QtWidgets.QListWidgetItem(a)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if a == "Ci" else QtCore.Qt.Unchecked)
            self.aov_list.addItem(item)
        self.status.setText(f"{len(aovs)} AOVs detected")
        if not self.output_edit.text().strip():
            self.output_edit.setText(self._default_output())

    def _selected(self) -> list:
        return [self.aov_list.item(i).text()
                for i in range(self.aov_list.count())
                if self.aov_list.item(i).checkState() == QtCore.Qt.Checked]

    def _run(self):
        self.model.set_input(self.input_edit.text().strip())
        self.model.select(self._selected())
        self.model.crossframe = self.cf.isChecked()
        self.model.flow = self.flow.isChecked()
        self.model.frames = self.frames.text().strip() or None
        self.model.tiles = None if self.tiles.currentText() == "off" else int(self.tiles.currentText())
        self.model.jobs = int(self.workers_combo.currentText())
        ok, msg = self.model.can_run()
        if not ok:
            QtWidgets.QMessageBox.warning(self, "Cannot run", msg)
            return
        out = self.output_edit.text().strip() or self._default_output()
        job = self.model.to_job(out)
        self.go.setEnabled(False)
        self.bar.setValue(0)
        self._console.clear()
        self._open_console()
        threading.Thread(target=self._run_worker, args=(job,), daemon=True).start()

    def _run_worker(self, job: DenoiseJob):
        try:
            exe = locate.find_denoise_batch(override=job.denoise_batch)
            code = runner.denoise_frames(exe, job,
                                         on_progress=self.sig_progress.emit,
                                         on_log=self.sig_log.emit)
        except Exception as exc:
            self.sig_log.emit(str(exc))
            code = 1
        self.sig_done.emit(code)

    def _on_done(self, code: int):
        self.go.setEnabled(True)
        self.sig_log.emit("Done." if code == 0 else f"Failed (exit {code}).")

    def _on_error(self, msg: str):
        self.status.setText("could not read AOVs")
        self.sig_log.emit(msg)


def main() -> int:
    # hython (RMDenoise.bat) already has a QApplication instance, so reuse any
    # existing one and only create a new one when there's none (e.g. plain
    # CPython with PySide). The window flashing then closing was caused by
    # keying "should I run the event loop?" off `app is None` — always False
    # under hython. Run our own event loop unless an interactive Houdini UI
    # (with its own running loop) is hosting us.
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    if not _IN_HOUDINI:
        return getattr(app, _EXEC)()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
