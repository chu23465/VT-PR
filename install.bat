@echo off
python -m pip install poetry
poetry config virtualenvs.in-project true
poetry install
pause