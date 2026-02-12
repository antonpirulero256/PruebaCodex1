from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response

from app.schemas import TranscriptionResponse
from app.transcription import Transcriber
from app.utils.subtitles import to_srt, to_vtt

MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")

transcriber = Transcriber(model_size=MODEL_SIZE, compute_type=COMPUTE_TYPE, device=DEVICE)

app = FastAPI(
    title="Open Source Multilingual Transcription API",
    version="0.1.0",
    description="API para transcribir audio en múltiples idiomas con faster-whisper.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE}


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

        result = transcriber.transcribe(
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
