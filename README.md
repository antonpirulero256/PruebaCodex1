# PruebaCodex1

MVP para transcripción de audio multilingüe con **IA open source** usando `faster-whisper` + FastAPI.

## Qué incluye

- Endpoint raíz `GET /` para descubrir rutas principales.
- Transcripción individual síncrona (`POST /transcribe`).
- Exportación individual (`POST /transcribe/export`).
- Transcripción por lotes asíncrona con cola Redis + RQ (`POST /transcribe/batch`).
- Consulta de estado de lotes y jobs (`GET /batches/{batch_id}`, `GET /jobs/{job_id}`).
- Descarga de resultados (`GET /jobs/{job_id}/download?format=...`).

## Requisitos

- Python 3.11+
- `ffmpeg` en el sistema (recomendado)

## Ejecución local (API)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Probar en Codespaces

1. Crea un Codespace desde el repositorio.
2. Espera a que termine `postCreateCommand` (crea `.venv` e instala dependencias).
3. Arranca la API:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

4. Abre el puerto reenviado `8000` y navega a `/docs`.

## Levantar stack completo (API + Redis + Worker)

```bash
docker compose up --build
```

Servicios:
- `api` en `http://localhost:8000`
- `redis` en `localhost:6379`
- `worker` escuchando cola `transcriptions`

## Endpoints compatibles (se mantienen)

- `GET /`
- `GET /health`
- `POST /transcribe`
- `POST /transcribe/export`

## Nuevos endpoints batch

- `POST /transcribe/batch`
- `GET /batches/{batch_id}`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/download?format=srt|vtt|txt|json`

## Ejemplos curl

### 1) Transcribir (JSON)

```bash
curl -X POST "http://localhost:8000/transcribe?beam_size=5&vad_filter=true" \
  -F "file=@audio1.mp3"
```

### 2) Exportar SRT/VTT (individual)

```bash
curl -X POST "http://localhost:8000/transcribe/export?format=srt" -F "file=@audio1.mp3"
curl -X POST "http://localhost:8000/transcribe/export?format=vtt" -F "file=@audio1.mp3"
```

### 3) Batch con 2 audios (campo `files` repetido en form-data)

```bash
curl -X POST "http://localhost:8000/transcribe/batch" \
  -F "files=@audio1.mp3" \
  -F "files=@audio2.wav" \
  -F "beam_size=5" \
  -F "vad_filter=true" \
  -F "export_formats=json" \
  -F "export_formats=srt" \
  -F "export_formats=vtt"
```

### 4) Consultar estado de batch

```bash
curl "http://localhost:8000/batches/<batch_id>"
```

### 5) Consultar un job y descargar resultados

```bash
curl "http://localhost:8000/jobs/<job_id>"
curl -OJ "http://localhost:8000/jobs/<job_id>/download?format=srt"
curl -OJ "http://localhost:8000/jobs/<job_id>/download?format=vtt"
```

## Estructura de salida por job

Cada job guarda datos en:

```text
data/batches/<batch_id>/<job_id>/
```

Archivos potenciales:
- `input.*`
- `meta.json`
- `result.json`
- `result.txt`
- `result.srt`
- `result.vtt`
- `error.txt` (si falla)

## Solución rápida si Codespaces parece “no arrancar”

Si en los logs ves líneas como `Outcome: success` y `Finished configuring codespace`, **el contenedor sí levantó correctamente**.

Para dejar el proyecto listo en cualquier reinicio:

```bash
bash .devcontainer/setup.sh
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Nota: es normal que Codespaces muestre imágenes base en logs internos (por ejemplo `devcontainers/base:alpine`) por su proceso de orquestación; el proyecto sigue usando la imagen Python 3.11 definida en `.devcontainer/devcontainer.json`.
