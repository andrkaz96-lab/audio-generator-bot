#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
python - << 'PY'
import torch

model, _ = torch.hub.load(
    repo_or_dir='snakers4/silero-models',
    model='silero_tts',
    language='ru',
    speaker='v4_ru',
)
print('Silero model is ready')
PY
