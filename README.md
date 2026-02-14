# PruebaCodex1

MVP para transcripción de audio multilingüe con **IA open source** usando `faster-whisper` + FastAPI.

## Qué incluye

- Página web simple integrada en la API (`GET /ui`) para usar funciones principales sin herramientas externas.
- Endpoint raíz `GET /` para descubrir rutas principales.
- Transcripción individual síncrona (`POST /transcribe`).
- Exportación individual (`POST /transcribe/export`).
- Transcripción por lotes asíncrona con cola Redis + RQ (`POST /transcribe/batch`).
- Previsualización de carpeta antes de encolar (`POST /transcribe/batch/folder/preview`).
- Transcripción por carpeta completa (`POST /transcribe/batch/folder`).
- Consulta de estado de lotes y jobs (`GET /batches/{batch_id}`, `GET /jobs/{job_id}`).
- Descarga de resultados (`GET /jobs/{job_id}/download?format=...`).
- Descarga masiva por lote en ZIP (`GET /batches/{batch_id}/download?format=all|txt|srt|vtt|json`).
- Descarga de TXT combinado por lote (`GET /batches/{batch_id}/download/txt`).
- Agrupación de varios lotes en un lote lógico (`POST /batch-groups`, `GET /batch-groups/{group_id}`).
- Descarga agregada por lote lógico en ZIP/TXT (`GET /batch-groups/{group_id}/download`, `GET /batch-groups/{group_id}/download/txt`).

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

Si aparece el error `No such image` para Redis, fuerza la descarga y recreación:

```bash
docker compose pull redis
docker compose up --build --force-recreate
```

Servicios:
- `api` en `http://localhost:8000`
- `redis` en `localhost:6379`
- `worker` escuchando cola `transcriptions`

Límite global opcional para lotes por carpeta:
- Variable de entorno `MAX_BATCH_FILES_DEFAULT` (ej. `500`).
- Aplica cuando no envías `max_files` en `/transcribe/batch/folder` y `/transcribe/batch/folder/preview`.

## Endpoints compatibles (se mantienen)

- `GET /`
- `GET /health`
- `GET /settings`
- `GET /ui`
- `POST /transcribe`
- `POST /transcribe/export`

## UI integrada

Tras levantar la API, abre:

```text
http://localhost:8000/ui
```

Desde ahí puedes:
- enviar carpeta local (selección desde navegador) a batch,
- encolar un archivo individual (uno por envío) desde el equipo,
- cargar varios archivos en una cola local y encolarlos de uno en uno (o todos en secuencia),
- quitar un archivo concreto de esa cola local por nombre (desplegable),
- al usar "encolar siguiente" repetidamente, la UI agrupa automáticamente los lotes en un `group_id`,
- agrupar automáticamente los chunks locales en un `group_id` único,
- hacer preview y enqueue de carpeta del servidor,
- consultar batches/jobs,
- consultar grupos lógicos (`group_id`) y descargar resultados agregados,
- descargar resultados (ZIP y TXT combinado),
- activar auto-refresh de estado de batch (cada 3s) hasta que termine.

Nota para carpetas locales grandes:
- La UI envía por bloques (configurable en "Archivos por envío", por defecto 25) para evitar errores tipo `Failed to fetch` por peticiones demasiado grandes.
- Archivos no-audio (ej. `.jpg`) se ignoran automáticamente.

## Nuevos endpoints batch

- `POST /transcribe/batch`
- `POST /transcribe/batch/folder/preview`
- `POST /transcribe/batch/folder`
- `GET /batches/{batch_id}`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/download?format=srt|vtt|txt|json`
- `GET /batches/{batch_id}/download?format=all|srt|vtt|txt|json`
- `GET /batches/{batch_id}/download/txt?label=job_id|filename&include_timestamps=true|false&include_metrics=true|false&include_empty_jobs=true|false&empty_placeholder=...&separator=rule|blank`
- `POST /batch-groups`
- `GET /batch-groups/{group_id}`
- `GET /batch-groups/{group_id}/download?format=all|srt|vtt|txt|json`
- `GET /batch-groups/{group_id}/download/txt?label=job_id|filename&include_timestamps=true|false&include_metrics=true|false&include_empty_jobs=true|false&empty_placeholder=...&separator=rule|blank`

## Guía rápida (usuario)

Si solo quieres usar la app sin entrar por terminal:

1. Sube audios con `POST /transcribe/batch`.
  - Si ya tienes los audios en una carpeta del servidor/contenedor, usa primero `POST /transcribe/batch/folder/preview` y luego `POST /transcribe/batch/folder`.
2. Copia el `batch_id` que devuelve la respuesta (o `group_id` si usaste subida local por chunks desde `/ui`).
3. Elige cómo quieres bajar resultados:

- **Un solo audio**: usa `GET /jobs/{job_id}/download?format=txt|srt|vtt|json`.
- **Todo el lote en ZIP**: usa `GET /batches/{batch_id}/download?format=all`.
- **Todo el lote en un TXT único**: usa `GET /batches/{batch_id}/download/txt`.
- **Varios lotes como uno solo**: crea un grupo con `POST /batch-groups` y descarga con `GET /batch-groups/{group_id}/download?...` o `GET /batch-groups/{group_id}/download/txt`.

Opciones útiles del TXT único:
- `label=filename` para mostrar nombre de archivo en vez de `job_id`.
- `include_timestamps=true` para incluir fechas.
- `include_metrics=false` para ocultar estado y tiempo.
- `include_empty_jobs=true` para incluir jobs sin resultado TXT.

Nota sobre `language` en Swagger:
- Si quieres autodetección, deja `language` vacío.
- No uses el placeholder `string` como idioma real.
- Si un batch ya se creó con jobs fallidos, ese batch no tendrá `result.*`; crea un batch nuevo para poder descargar resultados.

## Ejemplos curl

### 1) Transcribir (JSON)

```bash
curl -X POST "http://localhost:8000/transcribe?beam_size=5&vad_filter=true" \
  -F "file=@audio1.mp3"
```

### 1.1) Leer configuración para UI

```bash
curl "http://localhost:8000/settings"
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

### 4.1) Batch desde carpeta completa

```bash
# Preview: ver cuántos audios se encolarán
curl -X POST "http://localhost:8000/transcribe/batch/folder/preview" \
  -F "folder_path=/app/data/inbox" \
  -F "recursive=true"

# Preview con límite esperado
curl -X POST "http://localhost:8000/transcribe/batch/folder/preview" \
  -F "folder_path=/app/data/inbox" \
  -F "recursive=true" \
  -F "max_files=100"
```

```bash
# Encola todos los audios de una carpeta
curl -X POST "http://localhost:8000/transcribe/batch/folder" \
  -F "folder_path=/app/data/inbox" \
  -F "export_formats=txt" \
  -F "export_formats=srt"

# Incluyendo subcarpetas
curl -X POST "http://localhost:8000/transcribe/batch/folder" \
  -F "folder_path=/app/data/inbox" \
  -F "recursive=true" \
  -F "export_formats=txt"

# Con límite de seguridad (si hay más de 100 audios, responde 400)
curl -X POST "http://localhost:8000/transcribe/batch/folder" \
  -F "folder_path=/app/data/inbox" \
  -F "recursive=true" \
  -F "max_files=100" \
  -F "export_formats=txt"
```

### 5) Consultar un job y descargar resultados

```bash
curl "http://localhost:8000/jobs/<job_id>"
curl -OJ "http://localhost:8000/jobs/<job_id>/download?format=srt"
curl -OJ "http://localhost:8000/jobs/<job_id>/download?format=vtt"
```

### 6) Descargar un lote completo en ZIP

```bash
# Todos los formatos disponibles por job (json/txt/srt/vtt)
curl -OJ "http://localhost:8000/batches/<batch_id>/download?format=all"

# Solo TXT (si existe result.txt en los jobs)
curl -OJ "http://localhost:8000/batches/<batch_id>/download?format=txt"
```

### 7) Descargar un TXT combinado del lote

Cada bloque del TXT combinado incluye por defecto:
- `status`
- `process_time_seconds`

Puedes ocultarlos con `include_metrics=false`.

Si quieres incluir jobs sin `result.txt`, usa `include_empty_jobs=true`.
Puedes personalizar el texto mostrado con `empty_placeholder`.
El valor de `empty_placeholder` se sanea (sin saltos de línea, con espacios múltiples normalizados) y se recorta a 200 caracteres.

```bash
# Opción por defecto (encabezado con job_id y separador con regla)
curl -OJ "http://localhost:8000/batches/<batch_id>/download/txt"

# Encabezado con filename + timestamps + separador en blanco
curl -OJ "http://localhost:8000/batches/<batch_id>/download/txt?label=filename&include_timestamps=true&separator=blank"

# Sin métricas (solo encabezado + contenido)
curl -OJ "http://localhost:8000/batches/<batch_id>/download/txt?include_metrics=false"

# Incluir también jobs sin TXT
curl -OJ "http://localhost:8000/batches/<batch_id>/download/txt?include_empty_jobs=true"

# Incluir jobs sin TXT con mensaje personalizado
curl -OJ "http://localhost:8000/batches/<batch_id>/download/txt?include_empty_jobs=true&empty_placeholder=sin+transcripcion"
```

### 8) Lote lógico (agrupar varios batch_id)

```bash
# Crear grupo lógico con dos lotes
curl -X POST "http://localhost:8000/batch-groups" \
  -H "Content-Type: application/json" \
  -d '{"batch_ids": ["<batch_id_1>", "<batch_id_2>"], "name": "subida-local-enero"}'

# Consultar estado agregado del grupo
curl "http://localhost:8000/batch-groups/<group_id>"

# Descargar ZIP agregado de todos los jobs de todos los lotes del grupo
curl -OJ "http://localhost:8000/batch-groups/<group_id>/download?format=all"

# Descargar TXT combinado agregado
curl -OJ "http://localhost:8000/batch-groups/<group_id>/download/txt"
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

Si en VS Code (panel Containers/Images) ves **"Failed to connect. Is Docker installed?"**, suele ser porque el devcontainer aún no tiene habilitado acceso a Docker para esa extensión.
En este repo se habilita con la feature `docker-outside-of-docker`; tras actualizar, ejecuta **Rebuild Container** para que desaparezca ese aviso.

