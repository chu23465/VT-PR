@echo off
python -m pip install poetry==1.8.5
poetry config virtualenvs.in-project true
poetry lock --no-update
poetry install
pause