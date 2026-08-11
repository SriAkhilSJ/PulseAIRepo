@echo off
set PYTHONPATH=D:\pulseAIrepo\PulseAIRepo\.venv\Lib\site-packages
set PYTHONIOENCODING=utf-8
set LAB_THREAD=lab-chat-3
set LAB_OUT=report_chat_run3.json
"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.14.4-windows-x86_64-none\python.exe" "%~dp0run_eval_chat.py" %*
