@echo off
REM ===========================================================================
REM  Installs the ALTProtocol Houdini package so the RMDenoise shelf tool shows
REM  up inside Houdini. You do NOT edit any file by hand: this script writes a
REM  small pointer .json into Houdini's user "packages" folder, automatically
REM  filled in with the location of THIS repo.
REM
REM  Change HVER below if you run a different Houdini major.minor version.
REM ===========================================================================
setlocal

set "HVER=houdini21.0"

REM --- repo root = the folder this .bat lives in (drop the trailing backslash)
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

REM --- the package folder inside the repo, as a forward-slash path for JSON
set "ALTPATH=%REPO%\ALTProtocol"
set "ALTPATH=%ALTPATH:\=/%"

REM --- Houdini's user packages folder (create it if missing)
set "PKGDIR=%USERPROFILE%\Documents\%HVER%\packages"
if not exist "%PKGDIR%" mkdir "%PKGDIR%"

REM --- write the pointer file
> "%PKGDIR%\ALTProtocol.json" echo { "path": "%ALTPATH%" }

echo.
echo   Installed the ALTProtocol package.
echo   Wrote: %PKGDIR%\ALTProtocol.json
echo   Points at: %ALTPATH%
echo.
echo   Next:
echo     1. Start (or restart) Houdini.
echo     2. Click the small arrow / + at the left of the shelf-tab bar,
echo        open "Shelves", and enable "ALT Protocol".
echo     3. Click the RMDenoise tool.
echo.
echo   (If your Documents folder is redirected to OneDrive and the tool does not
echo    appear, move ALTProtocol.json into that OneDrive Houdini packages folder.)
echo.
pause
