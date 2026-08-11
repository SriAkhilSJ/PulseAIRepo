@echo off
set PYTHONPATH=D:\pulseAIrepo\PulseAIRepo\.venv\Lib\site-packages
set PYTHONIOENCODING=utf-8
if not defined LAB_THREAD set LAB_THREAD=lab-chat-d
if not defined LAB_OUT set LAB_OUT=report_chat_runD.json
"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.14.4-windows-x86_64-none\python.exe" "%~dp0run_eval_chat_d.py" %*
