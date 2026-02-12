# PruebaCodex1

MVP para transcripción de audio multilingüe con **IA open source** usando `faster-whisper` + FastAPI.

## Qué incluye

- API REST para transcribir audio (`/transcribe`).
- Detección automática de idioma (o idioma manual).
- Exportación de resultados en `txt`, `srt`, `vtt` o `json` (`/transcribe/export`).
- Preprocesado opcional con `ffmpeg` (mono, 16kHz) para mejorar robustez.
- Contenedor Docker listo para ejecutar.

## Requisitos

- Python 3.11+
- `ffmpeg` en el sistema (recomendado)

## Ejecución local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API en: `http://localhost:8000`

Swagger en: `http://localhost:8000/docs`

## Configuración del modelo

Variables de entorno:

- `WHISPER_MODEL` (default: `small`) — ejemplo: `base`, `small`, `medium`, `large-v3`
- `WHISPER_DEVICE` (default: `cpu`) — ejemplo: `cpu` o `cuda`
- `WHISPER_COMPUTE_TYPE` (default: `int8`) — ejemplo: `int8`, `float16`

## Uso con Docker

```bash
docker compose up --build
```

## Ejemplos de uso

### 1) Transcribir (JSON)

```bash
curl -X POST "http://localhost:8000/transcribe?beam_size=5&vad_filter=true" \
  -F "file=@mi_audio.mp3"
```

### 2) Exportar como texto plano

```bash
curl -X POST "http://localhost:8000/transcribe/export?format=txt" \
  -F "file=@mi_audio.mp3"
```

### 3) Exportar subtítulos SRT

```bash
curl -X POST "http://localhost:8000/transcribe/export?format=srt" \
  -F "file=@mi_audio.mp3"
```

### 4) Forzar idioma (ej. español)

```bash
curl -X POST "http://localhost:8000/transcribe?language=es" \
  -F "file=@mi_audio.mp3"
```

## Notas de producción

- Para mayor calidad, subir a `medium` o `large-v3`.
- Para más velocidad en CPU, usar `base` o `small`.
- Para alto volumen, añadir cola de trabajos (Redis + Celery/RQ).
- Si necesitas identificar hablantes, integrar diarización con `pyannote.audio`.
