from __future__ import annotations

from redis import Redis
from rq import Queue

from app.config import REDIS_URL, RQ_QUEUE


def get_redis_connection() -> Redis:
    return Redis.from_url(REDIS_URL)


def get_queue() -> Queue:
    return Queue(name=RQ_QUEUE, connection=get_redis_connection())


def enqueue_transcription_job(
    *,
    batch_id: str,
    job_id: str,
    input_path: str,
    language: str | None,
    beam_size: int,
    vad_filter: bool,
    export_formats: list[str],
):
    queue = get_queue()
    return queue.enqueue(
        "app.worker.process_transcription_job",
        kwargs={
            "batch_id": batch_id,
            "job_id": job_id,
            "input_path": input_path,
            "language": language,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "export_formats": export_formats,
        },
        job_id=job_id,
    )
