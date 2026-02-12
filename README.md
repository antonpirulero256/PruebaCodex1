# PruebaCodex1

MVP para transcripción de audio multilingüe con **IA open source** usando `faster-whisper` + FastAPI.

## Qué incluye

- Endpoint raíz `GET /` para descubrir rutas principales.
- API REST para transcribir audio (`POST /transcribe`).
- Detección automática de idioma (o idioma manual).
- Exportación de resultados en `txt`, `srt`, `vtt` o `json` (`POST /transcribe/export`).
- Endpoint de salud (`GET /health`).
- Preprocesado opcional con `ffmpeg` (mono, 16kHz) para mejorar robustez.
- Contenedor Docker y configuración de Codespaces.

## Requisitos

- Python 3.11+
- `ffmpeg` en el sistema (recomendado)

## Ejecución local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API en: `http://localhost:8000`

Swagger en: `http://localhost:8000/docs`

## Probar en Codespaces

1. Crea un Codespace desde el repositorio.
2. Espera a que termine `postCreateCommand` (crea `.venv` e instala dependencias).
3. Arranca la API:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

4. Abre el puerto reenviado `8000` en la pestaña **Ports** de Codespaces.
5. Navega a `https://<tu-url-codespaces>/docs` para abrir Swagger.

## Configuración del modelo

Variables de entorno:

- `WHISPER_MODEL` (default: `small`) — ejemplo: `base`, `small`, `medium`, `large-v3`
- `WHISPER_DEVICE` (default: `cpu`) — ejemplo: `cpu` o `cuda`
- `WHISPER_COMPUTE_TYPE` (default: `int8`) — ejemplo: `int8`, `float16`

## Uso con Docker

```bash
docker compose up --build
```

## Endpoints principales

- `GET /`
- `GET /health`
- `POST /transcribe`
- `POST /transcribe/export`

## Ejemplos curl

### 1) Transcribir (JSON)

```bash
curl -X POST "http://localhost:8000/transcribe?beam_size=5&vad_filter=true" \
  -F "file=@mi_audio.mp3"
```

### 2) Exportar subtítulos SRT

```bash
curl -X POST "http://localhost:8000/transcribe/export?format=srt" \
  -F "file=@mi_audio.mp3"
```

### 3) Exportar subtítulos VTT

```bash
curl -X POST "http://localhost:8000/transcribe/export?format=vtt" \
  -F "file=@mi_audio.mp3"
```

## Notas de producción

- Para mayor calidad, subir a `medium` o `large-v3`.
- Para más velocidad en CPU, usar `base` o `small`.
- Para alto volumen, añadir cola de trabajos (Redis + Celery/RQ).
- Si necesitas identificar hablantes, integrar diarización con `pyannote.audio`.
