from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))
BATCHES_ROOT = DATA_ROOT / "batches"
JOBS_INDEX_ROOT = DATA_ROOT / "jobs"

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RQ_QUEUE = os.getenv("RQ_QUEUE", "transcriptions")

MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
