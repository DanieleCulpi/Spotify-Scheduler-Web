@echo off
echo Cleaning old builds...
rmdir /s/q build
rmdir /s/q dist

echo Building Spotify Scheduler (Web Version)...
pyinstaller --noconfirm --onefile --windowed ^
    --icon "icon.ico" ^
    --name "spotify-scheduler" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "icon.ico;." ^
    --version-file "version.txt" ^
    "app.py"

echo.
echo Build complete! Check the "dist" folder.
pause
