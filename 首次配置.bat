@echo off
setlocal
cd /d "%~dp0"
if not exist "ai_config.json" (
    copy /Y "ai_config.example.json" "ai_config.json" >nul
    echo Created ai_config.json from the public template.
) else (
    echo ai_config.json already exists; opening it without overwriting.
)
echo.
echo Fill the chat API and realtime voice API fields, then save and close Notepad.
notepad "ai_config.json"
endlocal
