from __future__ import annotations

import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.config import COMPUTE_TYPE, DEVICE, MAX_BATCH_FILES_DEFAULT, MODEL_SIZE
from app.queueing import enqueue_transcription_job
from app.schemas import TranscriptionResponse
from app.storage import (
    batch_dir,
    batch_manifest_path,
    ensure_storage_dirs,
    find_batch_for_job,
    job_dir,
    job_meta_path,
    read_batch_group,
    read_json,
    save_batch_group,
    save_job_index,
    utc_now,
    write_json,
)
from app.transcription import get_transcriber
from app.utils.subtitles import to_srt, to_vtt

ALLOWED_EXPORT_FORMATS = {"json", "txt", "srt", "vtt"}
ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".opus",
    ".aac",
    ".webm",
    ".mp4",
    ".wma",
    ".aiff",
    ".aif",
}
DEFAULT_EMPTY_PLACEHOLDER = "[sin resultado txt para este job]"
MAX_EMPTY_PLACEHOLDER_LENGTH = 200
UI_FILE_PATH = Path(__file__).with_name("ui.html")


class BatchGroupCreateRequest(BaseModel):
    batch_ids: list[str] = Field(..., min_length=1)
    name: str | None = None


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _collect_group_jobs(batch_ids: list[str]) -> list[tuple[str, str, dict[str, object]]]:
    jobs: list[tuple[str, str, dict[str, object]]] = []
    for current_batch_id in batch_ids:
        current_manifest = read_json(batch_manifest_path(current_batch_id))
        for current_job_id in current_manifest.get("jobs", []):
            current_meta_path = job_meta_path(current_batch_id, current_job_id)
            current_meta = read_json(current_meta_path) if current_meta_path.exists() else {}
            jobs.append((current_batch_id, current_job_id, current_meta))
    return jobs


def _build_group_status_payload(group_payload: dict[str, object]) -> dict[str, object]:
    raw_batch_ids = group_payload.get("batch_ids", [])
    batch_ids = [str(batch_id) for batch_id in raw_batch_ids if isinstance(batch_id, str)]
    counters = {"queued": 0, "processing": 0, "done": 0, "failed": 0}
    batches_summary: list[dict[str, object]] = []

    for current_batch_id in batch_ids:
        current_batch = get_batch(current_batch_id)
        jobs = current_batch.get("jobs", [])
        batch_counters = {"queued": 0, "processing": 0, "done": 0, "failed": 0}
        for current_job in jobs:
            current_status = str(current_job.get("status", "")).lower()
            if current_status in counters:
                counters[current_status] += 1
                batch_counters[current_status] += 1

        batches_summary.append(
            {
                "batch_id": current_batch_id,
                "created_at": current_batch.get("created_at"),
                "total_jobs": current_batch.get("total_jobs", len(jobs)),
                "summary": batch_counters,
                "links": {
                    "batch": f"/batches/{current_batch_id}",
                    "download_zip": f"/batches/{current_batch_id}/download?format=all",
                    "download_txt": f"/batches/{current_batch_id}/download/txt",
                },
            }
        )

    total_jobs = sum(batch.get("total_jobs", 0) for batch in batches_summary)
    completed = total_jobs > 0 and (counters["done"] + counters["failed"] == total_jobs)

    return {
        "group_id": group_payload.get("group_id"),
        "name": group_payload.get("name"),
        "created_at": group_payload.get("created_at"),
        "batch_ids": batch_ids,
        "total_batches": len(batch_ids),
        "total_jobs": total_jobs,
        "summary": counters,
        "completed": completed,
        "batches": batches_summary,
        "links": {
            "download_zip": f"/batch-groups/{group_payload.get('group_id')}/download?format=all",
            "download_txt": f"/batch-groups/{group_payload.get('group_id')}/download/txt",
        },
    }


def _normalize_export_formats(export_formats: list[str] | None) -> list[str]:
    if not export_formats:
        return ["json", "txt", "srt", "vtt"]

    normalized: list[str] = []
    for raw_value in export_formats:
        for part in raw_value.split(","):
            candidate = part.strip().lower()
            if not candidate:
                continue
            normalized.append(candidate)

    if not normalized or normalized == ["string"]:
        return ["json", "txt", "srt", "vtt"]

    return normalized


def _sanitize_empty_placeholder(raw_value: str) -> str:
    sanitized = raw_value.replace("\r", " ").replace("\n", " ").strip()
    sanitized = " ".join(sanitized.split())
    if not sanitized:
        return DEFAULT_EMPTY_PLACEHOLDER
    return sanitized[:MAX_EMPTY_PLACEHOLDER_LENGTH]


def _normalize_language(language: str | None) -> str | None:
    if language is None:
        return None
    normalized = language.strip().lower()
    if normalized in {"", "string", "auto"}:
        return None
    return normalized


def _find_audio_files(source_folder: Path, recursive: bool) -> list[Path]:
    candidates = source_folder.rglob("*") if recursive else source_folder.iterdir()
    return sorted(
        [
            file_path
            for file_path in candidates
            if file_path.is_file() and file_path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
        ]
    )

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
        "endpoints": [
            "/ui",
            "/transcribe",
            "/transcribe/export",
            "/settings",
            "/transcribe/batch",
            "/transcribe/batch/folder/preview",
            "/transcribe/batch/folder",
            "/batch-groups",
            "/batch-groups/{group_id}",
            "/batch-groups/{group_id}/download",
            "/batch-groups/{group_id}/download/txt",
            "/batches/{batch_id}",
            "/batches/{batch_id}/download/txt",
            "/jobs/{job_id}",
            "/jobs/{job_id}/download?format=...",
            "/batches/{batch_id}/download?format=all|txt|srt|vtt|json",
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE, "compute_type": COMPUTE_TYPE}


@app.get("/ui")
def ui() -> FileResponse:
    if not UI_FILE_PATH.exists():
        raise HTTPException(status_code=500, detail="UI no disponible")
    return FileResponse(path=UI_FILE_PATH, media_type="text/html")


@app.get("/settings")
def settings() -> dict[str, object]:
    return {
        "batch": {
            "allowed_export_formats": sorted(ALLOWED_EXPORT_FORMATS),
            "allowed_audio_extensions": sorted(ALLOWED_AUDIO_EXTENSIONS),
            "max_batch_files_default": MAX_BATCH_FILES_DEFAULT,
        },
        "transcription": {
            "model": MODEL_SIZE,
            "device": DEVICE,
            "compute_type": COMPUTE_TYPE,
        },
    }


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(..., description="Archivo de audio a transcribir"),
    language: str | None = Query(default=None, description="Código de idioma opcional, ej. es/en/fr"),
    beam_size: int = Query(default=5, ge=1, le=10),
    vad_filter: bool = Query(default=True, description="Activa filtro VAD para silencios"),
) -> TranscriptionResponse:
    language = _normalize_language(language)
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
    language: str | None = Form(
        default=None,
        description="Idioma opcional (ej. es/en/fr). Déjalo vacío para autodetección.",
    ),
    beam_size: int = Form(default=5),
    vad_filter: bool = Form(default=True),
    export_formats: list[str] | None = Form(default=None),
) -> dict[str, object]:
    language = _normalize_language(language)
    if not files:
        raise HTTPException(status_code=400, detail="Debes enviar al menos un archivo en 'files'.")
    if beam_size < 1 or beam_size > 10:
        raise HTTPException(status_code=400, detail="beam_size debe estar entre 1 y 10.")

    chosen_formats = _normalize_export_formats(export_formats)
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


@app.post("/transcribe/batch/folder")
async def transcribe_batch_from_folder(
    folder_path: str = Form(..., description="Ruta de carpeta en el servidor/contenedor con audios."),
    recursive: bool = Form(default=False, description="Incluye subcarpetas si es true."),
    max_files: int | None = Form(default=None, description="Límite máximo de audios a encolar."),
    language: str | None = Form(
        default=None,
        description="Idioma opcional (ej. es/en/fr). Déjalo vacío para autodetección.",
    ),
    beam_size: int = Form(default=5),
    vad_filter: bool = Form(default=True),
    export_formats: list[str] | None = Form(default=None),
) -> dict[str, object]:
    language = _normalize_language(language)
    if beam_size < 1 or beam_size > 10:
        raise HTTPException(status_code=400, detail="beam_size debe estar entre 1 y 10.")
    if max_files is not None and max_files < 1:
        raise HTTPException(status_code=400, detail="max_files debe ser >= 1")
    effective_max_files = max_files if max_files is not None else MAX_BATCH_FILES_DEFAULT

    chosen_formats = _normalize_export_formats(export_formats)
    invalid = [fmt for fmt in chosen_formats if fmt not in ALLOWED_EXPORT_FORMATS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Formatos inválidos: {invalid}")

    source_folder = Path(folder_path).expanduser()
    if not source_folder.exists() or not source_folder.is_dir():
        raise HTTPException(status_code=400, detail="folder_path no existe o no es una carpeta")

    audio_files = _find_audio_files(source_folder, recursive)
    if not audio_files:
        raise HTTPException(status_code=400, detail="No se encontraron archivos de audio en la carpeta")
    if effective_max_files is not None and len(audio_files) > effective_max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Se encontraron {len(audio_files)} audios, supera max_files={effective_max_files}",
        )

    batch_id = str(uuid.uuid4())
    target_batch_dir = batch_dir(batch_id)
    target_batch_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[dict[str, object]] = []
    for audio_path in audio_files:
        job_id = str(uuid.uuid4())
        target_job_dir = job_dir(batch_id, job_id)
        target_job_dir.mkdir(parents=True, exist_ok=True)

        suffix = audio_path.suffix or ".tmp"
        input_file = target_job_dir / f"input{suffix}"
        input_file.write_bytes(audio_path.read_bytes())

        filename_for_meta = (
            str(audio_path.relative_to(source_folder)) if recursive else audio_path.name
        )
        meta = {
            "batch_id": batch_id,
            "job_id": job_id,
            "filename": filename_for_meta,
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

        jobs.append({"job_id": job_id, "filename": filename_for_meta, "status": meta["status"]})

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
        "source_folder": str(source_folder),
        "max_files": effective_max_files,
        "links": {"batch": f"/batches/{batch_id}"},
    }


@app.post("/transcribe/batch/folder/preview")
async def preview_batch_from_folder(
    folder_path: str = Form(..., description="Ruta de carpeta en el servidor/contenedor con audios."),
    recursive: bool = Form(default=False, description="Incluye subcarpetas si es true."),
    max_files: int | None = Form(default=None, description="Límite máximo esperado de audios."),
) -> dict[str, object]:
    if max_files is not None and max_files < 1:
        raise HTTPException(status_code=400, detail="max_files debe ser >= 1")
    effective_max_files = max_files if max_files is not None else MAX_BATCH_FILES_DEFAULT

    source_folder = Path(folder_path).expanduser()
    if not source_folder.exists() or not source_folder.is_dir():
        raise HTTPException(status_code=400, detail="folder_path no existe o no es una carpeta")

    audio_files = _find_audio_files(source_folder, recursive)
    relative_audio_files = [str(path.relative_to(source_folder)) for path in audio_files]
    exceeds_limit = effective_max_files is not None and len(relative_audio_files) > effective_max_files

    return {
        "source_folder": str(source_folder),
        "recursive": recursive,
        "max_files": effective_max_files,
        "total_files": len(relative_audio_files),
        "exceeds_limit": exceeds_limit,
        "audio_files": relative_audio_files,
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


@app.post("/batch-groups")
def create_batch_group(request: BatchGroupCreateRequest) -> dict[str, object]:
    cleaned_batch_ids = _unique_preserve_order([batch_id.strip() for batch_id in request.batch_ids if batch_id.strip()])
    if not cleaned_batch_ids:
        raise HTTPException(status_code=400, detail="Debes enviar al menos un batch_id válido")

    missing = [batch_id for batch_id in cleaned_batch_ids if not batch_manifest_path(batch_id).exists()]
    if missing:
        raise HTTPException(status_code=404, detail=f"batch_id no encontrado: {missing}")

    group_id = str(uuid.uuid4())
    payload = {
        "group_id": group_id,
        "name": request.name,
        "batch_ids": cleaned_batch_ids,
        "created_at": utc_now(),
    }
    save_batch_group(group_id, payload)

    return {
        "group_id": group_id,
        "name": request.name,
        "batch_ids": cleaned_batch_ids,
        "total_batches": len(cleaned_batch_ids),
        "links": {
            "group": f"/batch-groups/{group_id}",
            "download_zip": f"/batch-groups/{group_id}/download?format=all",
            "download_txt": f"/batch-groups/{group_id}/download/txt",
        },
    }


@app.get("/batch-groups/{group_id}")
def get_batch_group(group_id: str) -> dict[str, object]:
    payload = read_batch_group(group_id)
    if not payload:
        raise HTTPException(status_code=404, detail="group_id no encontrado")
    return _build_group_status_payload(payload)


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


@app.get("/batches/{batch_id}/download")
def download_batch_results(
    batch_id: str,
    format: str = Query(default="all", pattern="^(all|txt|srt|vtt|json)$"),
) -> StreamingResponse:
    manifest_path = batch_manifest_path(batch_id)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="batch_id no encontrado")

    manifest = read_json(manifest_path)
    job_ids = manifest.get("jobs", [])

    requested_formats = ["json", "txt", "srt", "vtt"] if format == "all" else [format]
    zip_buffer = io.BytesIO()
    files_added = 0

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for current_job_id in job_ids:
            current_job_dir = job_dir(batch_id, current_job_id)
            for current_format in requested_formats:
                result_path = current_job_dir / f"result.{current_format}"
                if not result_path.exists():
                    continue
                zip_file.write(result_path, arcname=f"{current_job_id}/result.{current_format}")
                files_added += 1

    if files_added == 0:
        raise HTTPException(status_code=404, detail="No hay resultados disponibles para ese batch/formato")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-results.zip"'},
    )


@app.get("/batch-groups/{group_id}/download")
def download_batch_group_results(
    group_id: str,
    format: str = Query(default="all", pattern="^(all|txt|srt|vtt|json)$"),
) -> StreamingResponse:
    group_payload = read_batch_group(group_id)
    if not group_payload:
        raise HTTPException(status_code=404, detail="group_id no encontrado")

    raw_batch_ids = group_payload.get("batch_ids", [])
    batch_ids = [str(batch_id) for batch_id in raw_batch_ids if isinstance(batch_id, str)]
    requested_formats = ["json", "txt", "srt", "vtt"] if format == "all" else [format]
    zip_buffer = io.BytesIO()
    files_added = 0

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for current_batch_id in batch_ids:
            current_manifest = read_json(batch_manifest_path(current_batch_id))
            for current_job_id in current_manifest.get("jobs", []):
                current_job_dir = job_dir(current_batch_id, current_job_id)
                for current_format in requested_formats:
                    result_path = current_job_dir / f"result.{current_format}"
                    if not result_path.exists():
                        continue
                    zip_file.write(
                        result_path,
                        arcname=f"{current_batch_id}/{current_job_id}/result.{current_format}",
                    )
                    files_added += 1

    if files_added == 0:
        raise HTTPException(status_code=404, detail="No hay resultados disponibles para ese group/formato")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{group_id}-results.zip"'},
    )


@app.get("/batches/{batch_id}/download/txt")
def download_batch_combined_txt(
    batch_id: str,
    label: str = Query(default="job_id", pattern="^(job_id|filename)$"),
    include_timestamps: bool = Query(default=False),
    include_metrics: bool = Query(default=True),
    include_empty_jobs: bool = Query(default=False),
    empty_placeholder: str = Query(default=DEFAULT_EMPTY_PLACEHOLDER),
    separator: str = Query(default="rule", pattern="^(rule|blank)$"),
) -> PlainTextResponse:
    manifest_path = batch_manifest_path(batch_id)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="batch_id no encontrado")

    manifest = read_json(manifest_path)
    combined_parts: list[str] = []
    section_separator = "\n\n---\n\n" if separator == "rule" else "\n\n"
    safe_empty_placeholder = _sanitize_empty_placeholder(empty_placeholder)

    for current_job_id in manifest.get("jobs", []):
        txt_path = job_dir(batch_id, current_job_id) / "result.txt"
        meta_path = job_meta_path(batch_id, current_job_id)
        job_meta = read_json(meta_path) if meta_path.exists() else {}
        header_value = (
            job_meta.get("filename") or current_job_id
            if label == "filename"
            else current_job_id
        )

        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8").strip()
        elif include_empty_jobs:
            content = safe_empty_placeholder
        else:
            continue

        section_lines = [f"## {header_value}"]
        if include_metrics:
            section_lines.append(f"status: {job_meta.get('status', 'N/A')}")
            section_lines.append(f"process_time_seconds: {job_meta.get('process_time_seconds', 'N/A')}")
        if include_timestamps:
            section_lines.append(f"created_at: {job_meta.get('created_at', 'N/A')}")
            section_lines.append(f"finished_at: {job_meta.get('finished_at', 'N/A')}")
        section_lines.append("")
        section_lines.append(content)
        combined_parts.append("\n".join(section_lines))

    if not combined_parts:
        raise HTTPException(status_code=404, detail="No hay resultados TXT disponibles para ese batch")

    return PlainTextResponse(
        content=section_separator.join(combined_parts),
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-combined.txt"'},
    )


@app.get("/batch-groups/{group_id}/download/txt")
def download_batch_group_combined_txt(
    group_id: str,
    label: str = Query(default="job_id", pattern="^(job_id|filename)$"),
    include_timestamps: bool = Query(default=False),
    include_metrics: bool = Query(default=True),
    include_empty_jobs: bool = Query(default=False),
    empty_placeholder: str = Query(default=DEFAULT_EMPTY_PLACEHOLDER),
    separator: str = Query(default="rule", pattern="^(rule|blank)$"),
) -> PlainTextResponse:
    group_payload = read_batch_group(group_id)
    if not group_payload:
        raise HTTPException(status_code=404, detail="group_id no encontrado")

    raw_batch_ids = group_payload.get("batch_ids", [])
    batch_ids = [str(batch_id) for batch_id in raw_batch_ids if isinstance(batch_id, str)]
    combined_parts: list[str] = []
    section_separator = "\n\n---\n\n" if separator == "rule" else "\n\n"
    safe_empty_placeholder = _sanitize_empty_placeholder(empty_placeholder)

    for current_batch_id, current_job_id, job_meta in _collect_group_jobs(batch_ids):
        txt_path = job_dir(current_batch_id, current_job_id) / "result.txt"
        filename = job_meta.get("filename") or current_job_id
        header_source = filename if label == "filename" else current_job_id
        header_value = f"{current_batch_id}/{header_source}"

        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8").strip()
        elif include_empty_jobs:
            content = safe_empty_placeholder
        else:
            continue

        section_lines = [f"## {header_value}"]
        if include_metrics:
            section_lines.append(f"status: {job_meta.get('status', 'N/A')}")
            section_lines.append(f"process_time_seconds: {job_meta.get('process_time_seconds', 'N/A')}")
        if include_timestamps:
            section_lines.append(f"created_at: {job_meta.get('created_at', 'N/A')}")
            section_lines.append(f"finished_at: {job_meta.get('finished_at', 'N/A')}")
        section_lines.append("")
        section_lines.append(content)
        combined_parts.append("\n".join(section_lines))

    if not combined_parts:
        raise HTTPException(status_code=404, detail="No hay resultados TXT disponibles para ese grupo")

    return PlainTextResponse(
        content=section_separator.join(combined_parts),
        headers={"Content-Disposition": f'attachment; filename="{group_id}-combined.txt"'},
    )
