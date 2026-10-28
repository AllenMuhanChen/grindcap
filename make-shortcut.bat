@echo off
rem Puts a "grindcap" shortcut on your Desktop that opens the control window.
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\grindcap.lnk'); $s.TargetPath='%~dp0grindcap.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Desktop shortcut created.
pause
