@echo off
REM Launch the RenderMan Denoiser GUI under Houdini's bundled Python (PySide2).
REM Adjust HFS if your Houdini install path differs.
set "HFS=C:\Program Files\Side Effects Software\Houdini 21.0.559"

REM Force Qt to use Houdini's own (Qt5) plugins. Without this, if RenderMan's
REM setup put its Qt-6.5.3 on the environment, Qt5 scans those incompatible
REM plugins ("Invalid metadata version") and startup is slow.
set "QT_PLUGIN_PATH=%HFS%\bin\Qt_plugins"
set "QT_QPA_PLATFORM_PLUGIN_PATH=%HFS%\bin\Qt_plugins\platforms"

"%HFS%\bin\hython.exe" -c "import sys,os; sys.path.insert(0, os.path.dirname(r'%~dp0x')); from rman_denoiser.gui import main; main()"
