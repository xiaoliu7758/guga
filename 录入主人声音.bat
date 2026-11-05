@echo off
cd /d "%~dp0"
if not exist "resources\models\speaker\3dspeaker_eres2net_base_16k.onnx" (
  python tools\download_speaker_model.py
  if errorlevel 1 pause & exit /b 1
)
python tools\enroll_voice_owner.py
pause
