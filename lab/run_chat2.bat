@echo off
set PYTHONPATH=D:\pulseAIrepo\PulseAIRepo\.venv\Lib\site-packages
set PYTHONIOENCODING=utf-8
set LAB_THREAD=lab-chat-2
set LAB_OUT=report_chat_run2.json
set LAB_TASK_EXTRA=IMPORTANT: The workspace is intentionally empty - that is the test. Do NOT ask for permission or clarification, do NOT stop to ask the user. Scaffold the Next.js app yourself (create package.json, install dependencies with npm, write all components) and build the full chat interface exactly as specified, then verify it in the browser with the browser tools.
"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.14.4-windows-x86_64-none\python.exe" "%~dp0run_eval_chat.py" %*
