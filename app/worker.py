from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import COMPUTE_TYPE, DEVICE, MODEL_SIZE
from app.storage import job_dir, job_meta_path, read_json, utc_now, write_json
from app.transcription import get_transcriber
from app.utils.subtitles import to_srt, to_vtt


def _update_meta(batch_id: str, job_id: str, **fields) -> dict:
    path = job_meta_path(batch_id, job_id)
    payload = read_json(path)
    payload.update(fields)
    payload["updated_at"] = utc_now()
    write_json(path, payload)
    return payload


def process_transcription_job(
    *,
    batch_id: str,
    job_id: str,
    input_path: str,
    language: str | None,
    beam_size: int,
    vad_filter: bool,
    export_formats: list[str],
) -> None:
    start_ts = time.perf_counter()
    _update_meta(batch_id, job_id, status="processing", started_at=utc_now())
    target_dir = job_dir(batch_id, job_id)

    try:
        transcriber = get_transcriber()
        result = transcriber.transcribe(
            audio_path=Path(input_path),
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )

        result_files: dict[str, str] = {}
        if "json" in export_formats:
            path_json = target_dir / "result.json"
            path_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result_files["json"] = str(path_json)
        if "txt" in export_formats:
            path_txt = target_dir / "result.txt"
            path_txt.write_text(result.get("text", ""), encoding="utf-8")
            result_files["txt"] = str(path_txt)
        if "srt" in export_formats:
            path_srt = target_dir / "result.srt"
            path_srt.write_text(to_srt(result.get("segments", [])), encoding="utf-8")
            result_files["srt"] = str(path_srt)
        if "vtt" in export_formats:
            path_vtt = target_dir / "result.vtt"
            path_vtt.write_text(to_vtt(result.get("segments", [])), encoding="utf-8")
            result_files["vtt"] = str(path_vtt)

        process_time = round(time.perf_counter() - start_ts, 3)
        _update_meta(
            batch_id,
            job_id,
            status="done",
            finished_at=utc_now(),
            process_time_seconds=process_time,
            audio_duration_seconds=result.get("duration"),
            model=MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            detected_language=result.get("language"),
            result_files=result_files,
        )
    except Exception as exc:  # noqa: BLE001
        (target_dir / "error.txt").write_text(str(exc), encoding="utf-8")
        _update_meta(
            batch_id,
            job_id,
            status="failed",
            finished_at=utc_now(),
            process_time_seconds=round(time.perf_counter() - start_ts, 3),
            error=str(exc),
            model=MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
        )
