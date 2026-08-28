@echo off
cd /d "%~dp0"
call .venv\Scripts\streamlit.exe run streamlit_app.py
