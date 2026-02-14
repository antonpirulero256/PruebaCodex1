from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import COMPUTE_TYPE, DEVICE, MODEL_SIZE
from app.queueing import enqueue_transcription_job
from app.schemas import TranscriptionResponse
from app.storage import (
    batch_dir,
    batch_manifest_path,
    ensure_storage_dirs,
    find_batch_for_job,
    job_dir,
    job_meta_path,
    read_json,
    save_job_index,
    utc_now,
    write_json,
)
from app.transcription import get_transcriber
from app.utils.subtitles import to_srt, to_vtt

ALLOWED_EXPORT_FORMATS = {"json", "txt", "srt", "vtt"}

app = FastAPI(
    title="Open Source Multilingual Transcription API",
    version="0.2.0",
    description="API para transcribir audio en múltiples idiomas con faster-whisper + cola Redis/RQ.",
)

ensure_storage_dirs()


@app.get("/")
def root() -> dict[str, object]:
    return {
        "ok": True,
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/transcribe", "/transcribe/export"],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE, "compute_type": COMPUTE_TYPE}


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(..., description="Archivo de audio a transcribir"),
    language: str | None = Query(default=None, description="Código de idioma opcional, ej. es/en/fr"),
    beam_size: int = Query(default=5, ge=1, le=10),
    vad_filter: bool = Query(default=True, description="Activa filtro VAD para silencios"),
) -> TranscriptionResponse:
    suffix = Path(file.filename or "audio").suffix or ".tmp"
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            content = await file.read()
            temp_file.write(content)

        result = get_transcriber().transcribe(
            audio_path=temp_path,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        return TranscriptionResponse(**result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcripción falló: {exc}") from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


@app.post("/transcribe/export")
async def transcribe_and_export(
    file: UploadFile = File(...),
    format: str = Query(default="txt", pattern="^(txt|srt|vtt|json)$"),
    language: str | None = Query(default=None),
    beam_size: int = Query(default=5, ge=1, le=10),
    vad_filter: bool = Query(default=True),
) -> Response:
    transcription = await transcribe_audio(
        file=file,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
    )

    if format == "txt":
        return PlainTextResponse(content=transcription.text)
    if format == "json":
        return Response(
            content=json.dumps(transcription.model_dump(), ensure_ascii=False, indent=2),
            media_type="application/json",
        )
    if format == "srt":
        return PlainTextResponse(content=to_srt([s.model_dump() for s in transcription.segments]))

    return PlainTextResponse(content=to_vtt([s.model_dump() for s in transcription.segments]))


@app.post("/transcribe/batch")
async def transcribe_batch(
    files: list[UploadFile] = File(..., description="Uno o más archivos de audio"),
    language: str | None = Form(default=None),
    beam_size: int = Form(default=5),
    vad_filter: bool = Form(default=True),
    export_formats: list[str] | None = Form(default=None),
) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="Debes enviar al menos un archivo en 'files'.")
    if beam_size < 1 or beam_size > 10:
        raise HTTPException(status_code=400, detail="beam_size debe estar entre 1 y 10.")

    chosen_formats = export_formats or ["json", "txt", "srt", "vtt"]
    invalid = [fmt for fmt in chosen_formats if fmt not in ALLOWED_EXPORT_FORMATS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Formatos inválidos: {invalid}")

    batch_id = str(uuid.uuid4())
    target_batch_dir = batch_dir(batch_id)
    target_batch_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[dict[str, object]] = []
    for uploaded in files:
        job_id = str(uuid.uuid4())
        target_job_dir = job_dir(batch_id, job_id)
        target_job_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(uploaded.filename or "audio").suffix or ".tmp"
        input_file = target_job_dir / f"input{suffix}"
        content = await uploaded.read()
        input_file.write_bytes(content)

        meta = {
            "batch_id": batch_id,
            "job_id": job_id,
            "filename": uploaded.filename,
            "status": "queued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "language": language,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "export_formats": chosen_formats,
            "input_path": str(input_file),
            "result_files": {},
        }
        write_json(job_meta_path(batch_id, job_id), meta)
        save_job_index(job_id, batch_id)

        try:
            enqueue_transcription_job(
                batch_id=batch_id,
                job_id=job_id,
                input_path=str(input_file),
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                export_formats=chosen_formats,
            )
        except Exception as exc:  # noqa: BLE001
            (target_job_dir / "error.txt").write_text(str(exc), encoding="utf-8")
            meta["status"] = "failed"
            meta["error"] = str(exc)
            meta["updated_at"] = utc_now()
            write_json(job_meta_path(batch_id, job_id), meta)

        jobs.append({"job_id": job_id, "filename": uploaded.filename, "status": meta["status"]})

    manifest = {
        "batch_id": batch_id,
        "created_at": utc_now(),
        "jobs": [item["job_id"] for item in jobs],
        "total_jobs": len(jobs),
    }
    write_json(batch_manifest_path(batch_id), manifest)

    return {
        "batch_id": batch_id,
        "status": "queued",
        "jobs": jobs,
        "links": {"batch": f"/batches/{batch_id}"},
    }


@app.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> dict[str, object]:
    manifest_path = batch_manifest_path(batch_id)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="batch_id no encontrado")

    manifest = read_json(manifest_path)
    jobs_summary: list[dict[str, object]] = []
    for job_id in manifest.get("jobs", []):
        meta_path = job_meta_path(batch_id, job_id)
        if not meta_path.exists():
            continue
        meta = read_json(meta_path)
        jobs_summary.append(
            {
                "job_id": job_id,
                "filename": meta.get("filename"),
                "status": meta.get("status"),
                "job_detail": f"/jobs/{job_id}",
                "downloads": {
                    fmt: f"/jobs/{job_id}/download?format={fmt}"
                    for fmt in meta.get("export_formats", [])
                    if (job_dir(batch_id, job_id) / f"result.{fmt}").exists()
                },
            }
        )

    return {
        "batch_id": batch_id,
        "created_at": manifest.get("created_at"),
        "total_jobs": manifest.get("total_jobs", len(jobs_summary)),
        "jobs": jobs_summary,
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    batch_id = find_batch_for_job(job_id)
    if not batch_id:
        raise HTTPException(status_code=404, detail="job_id no encontrado")

    meta_path = job_meta_path(batch_id, job_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="job metadata no encontrado")

    meta = read_json(meta_path)
    downloads = {
        fmt: f"/jobs/{job_id}/download?format={fmt}"
        for fmt in meta.get("export_formats", [])
        if (job_dir(batch_id, job_id) / f"result.{fmt}").exists()
    }
    meta["downloads"] = downloads
    return meta


@app.get("/jobs/{job_id}/download")
def download_job_result(job_id: str, format: str = Query(..., pattern="^(txt|srt|vtt|json)$")) -> FileResponse:
    batch_id = find_batch_for_job(job_id)
    if not batch_id:
        raise HTTPException(status_code=404, detail="job_id no encontrado")

    output_path = job_dir(batch_id, job_id) / f"result.{format}"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail=f"Resultado '{format}' no disponible")

    media_type = {
        "txt": "text/plain",
        "srt": "text/plain",
        "vtt": "text/vtt",
        "json": "application/json",
    }[format]
    return FileResponse(path=output_path, media_type=media_type, filename=f"{job_id}.{format}")
