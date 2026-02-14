from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))
BATCHES_ROOT = DATA_ROOT / "batches"
JOBS_INDEX_ROOT = DATA_ROOT / "jobs"
BATCH_GROUPS_ROOT = DATA_ROOT / "batch_groups"

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RQ_QUEUE = os.getenv("RQ_QUEUE", "transcriptions")

MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")


def _read_positive_int_env(var_name: str) -> int | None:
	raw_value = os.getenv(var_name)
	if raw_value is None or raw_value.strip() == "":
		return None
	try:
		parsed = int(raw_value)
	except ValueError:
		return None
	return parsed if parsed >= 1 else None


MAX_BATCH_FILES_DEFAULT = _read_positive_int_env("MAX_BATCH_FILES_DEFAULT")
