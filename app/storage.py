from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BATCHES_ROOT, JOBS_INDEX_ROOT


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_storage_dirs() -> None:
    BATCHES_ROOT.mkdir(parents=True, exist_ok=True)
    JOBS_INDEX_ROOT.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def batch_dir(batch_id: str) -> Path:
    return BATCHES_ROOT / batch_id


def batch_manifest_path(batch_id: str) -> Path:
    return batch_dir(batch_id) / "batch.json"


def job_dir(batch_id: str, job_id: str) -> Path:
    return batch_dir(batch_id) / job_id


def job_meta_path(batch_id: str, job_id: str) -> Path:
    return job_dir(batch_id, job_id) / "meta.json"


def job_index_path(job_id: str) -> Path:
    return JOBS_INDEX_ROOT / f"{job_id}.json"


def save_job_index(job_id: str, batch_id: str) -> None:
    write_json(job_index_path(job_id), {"job_id": job_id, "batch_id": batch_id})


def find_batch_for_job(job_id: str) -> str | None:
    idx = job_index_path(job_id)
    if not idx.exists():
        return None
    return read_json(idx).get("batch_id")
