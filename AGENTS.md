# Agent instructions for this repository

## Local setup
1. `python -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements-dev.txt`

## Checks
- Tests: `PYTHONPATH=. pytest -q`
- Lint: `ruff check .`
- Format: `ruff format .`

## Done criteria for mode-routing task
- Три режима URL пайплайна работают: `close_to_source`, `audio_adapted`, `audio_summary`.
- Backward compatibility alias'ы (`near_verbatim`, `readable_cleaned`) сохраняются.
- Есть anti-hallucination verification/repair path и hard cap duration enforcement.
- Добавлены/обновлены тесты на роутинг, нормализацию и ограничения длительности.
