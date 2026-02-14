from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
import app.storage as storage_module


def _patch_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "BATCHES_ROOT", tmp_path / "batches")
    monkeypatch.setattr(storage_module, "JOBS_INDEX_ROOT", tmp_path / "jobs")
    storage_module.ensure_storage_dirs()


def test_settings_endpoint_returns_runtime_configuration() -> None:
    client = TestClient(main_module.app)
    response = client.get("/settings")

    assert response.status_code == 200
    payload = response.json()
    assert "batch" in payload
    assert "transcription" in payload
    assert "allowed_export_formats" in payload["batch"]
    assert "allowed_audio_extensions" in payload["batch"]
    assert "max_batch_files_default" in payload["batch"]


def test_ui_endpoint_is_available() -> None:
    client = TestClient(main_module.app)
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_batch_endpoint_accepts_multiple_files(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    enqueued: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        enqueued.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch",
        files=[
            ("files", ("audio1.wav", b"fake-audio-1", "audio/wav")),
            ("files", ("audio2.mp3", b"fake-audio-2", "audio/mpeg")),
        ],
        data=[("export_formats", "json"), ("export_formats", "srt")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert "batch_id" in payload
    assert len(payload["jobs"]) == 2
    assert all(job["status"] == "queued" for job in payload["jobs"])
    assert len(enqueued) == 2


def test_batch_and_job_status_endpoints_return_queued_state(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
    )
    assert create.status_code == 200
    created = create.json()

    batch_id = created["batch_id"]
    job_id = created["jobs"][0]["job_id"]

    batch_resp = client.get(f"/batches/{batch_id}")
    assert batch_resp.status_code == 200
    batch_payload = batch_resp.json()
    assert batch_payload["batch_id"] == batch_id
    assert batch_payload["jobs"][0]["status"] == "queued"

    job_resp = client.get(f"/jobs/{job_id}")
    assert job_resp.status_code == 200
    job_payload = job_resp.json()
    assert job_payload["job_id"] == job_id
    assert job_payload["status"] == "queued"
    assert job_payload["batch_id"] == batch_id

    job_dir = Path(storage_module.job_dir(batch_id, job_id))
    assert (job_dir / "meta.json").exists()


def test_batch_endpoint_accepts_swagger_placeholder_string(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    captured: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "string")],
    )

    assert response.status_code == 200
    assert captured[0]["export_formats"] == ["json", "txt", "srt", "vtt"]


def test_batch_endpoint_accepts_csv_export_formats(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    captured: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "json,srt")],
    )

    assert response.status_code == 200
    assert captured[0]["export_formats"] == ["json", "srt"]


def test_batch_endpoint_normalizes_swagger_language_placeholder(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    captured: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("language", "string")],
    )

    assert response.status_code == 200
    assert captured[0]["language"] is None


def test_batch_folder_endpoint_enqueues_audio_files(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "audios"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.wav").write_bytes(b"fake-audio-1")
    (source / "b.mp3").write_bytes(b"fake-audio-2")
    (source / "note.txt").write_text("not audio", encoding="utf-8")

    captured: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder",
        data=[("folder_path", str(source)), ("export_formats", "txt")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_folder"] == str(source)
    assert len(payload["jobs"]) == 2
    assert len(captured) == 2


def test_batch_folder_endpoint_returns_400_without_audio_files(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "empty_audios"
    source.mkdir(parents=True, exist_ok=True)
    (source / "note.txt").write_text("not audio", encoding="utf-8")

    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder",
        data=[("folder_path", str(source)), ("export_formats", "txt")],
    )

    assert response.status_code == 400


def test_batch_folder_endpoint_recursive_includes_subfolders(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "audios_recursive"
    nested = source / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "deep.opus").write_bytes(b"fake-audio-deep")

    captured: list[dict] = []

    def fake_enqueue_transcription_job(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(main_module, "enqueue_transcription_job", fake_enqueue_transcription_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder",
        data=[("folder_path", str(source)), ("recursive", "true"), ("export_formats", "txt")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["filename"] == "nested/deep.opus"


def test_batch_folder_endpoint_respects_max_files_limit(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "audios_limit"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.wav").write_bytes(b"fake-audio-1")
    (source / "b.mp3").write_bytes(b"fake-audio-2")

    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder",
        data=[("folder_path", str(source)), ("max_files", "1"), ("export_formats", "txt")],
    )

    assert response.status_code == 400


def test_batch_folder_preview_includes_exceeds_limit_flag(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_limit"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.wav").write_bytes(b"fake-audio-1")
    (source / "b.mp3").write_bytes(b"fake-audio-2")

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source)), ("max_files", "1")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 2
    assert payload["max_files"] == 1
    assert payload["exceeds_limit"] is True


def test_batch_folder_preview_rejects_invalid_max_files(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_invalid_limit"
    source.mkdir(parents=True, exist_ok=True)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source)), ("max_files", "0")],
    )

    assert response.status_code == 400


def test_batch_folder_endpoint_uses_default_max_files_from_config(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "audios_default_limit"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.wav").write_bytes(b"fake-audio-1")
    (source / "b.mp3").write_bytes(b"fake-audio-2")

    monkeypatch.setattr(main_module, "MAX_BATCH_FILES_DEFAULT", 1)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder",
        data=[("folder_path", str(source)), ("export_formats", "txt")],
    )

    assert response.status_code == 400


def test_batch_folder_preview_uses_default_max_files_from_config(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_default_limit"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.wav").write_bytes(b"fake-audio-1")
    (source / "b.mp3").write_bytes(b"fake-audio-2")

    monkeypatch.setattr(main_module, "MAX_BATCH_FILES_DEFAULT", 1)

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["max_files"] == 1
    assert payload["exceeds_limit"] is True


def test_batch_folder_preview_non_recursive(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_non_recursive"
    nested = source / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (source / "top.wav").write_bytes(b"fake-audio-top")
    (nested / "deep.opus").write_bytes(b"fake-audio-deep")

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source)), ("recursive", "false")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 1
    assert payload["audio_files"] == ["top.wav"]


def test_batch_folder_preview_recursive(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_recursive"
    nested = source / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (source / "top.wav").write_bytes(b"fake-audio-top")
    (nested / "deep.opus").write_bytes(b"fake-audio-deep")

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source)), ("recursive", "true")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 2
    assert payload["audio_files"] == ["nested/deep.opus", "top.wav"]


def test_batch_folder_preview_empty_folder(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)

    source = tmp_path / "preview_empty"
    source.mkdir(parents=True, exist_ok=True)
    (source / "note.txt").write_text("not audio", encoding="utf-8")

    client = TestClient(main_module.app)
    response = client.post(
        "/transcribe/batch/folder/preview",
        data=[("folder_path", str(source)), ("recursive", "true")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 0
    assert payload["audio_files"] == []


def test_download_batch_results_as_zip(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt"), ("export_formats", "srt")],
    )
    assert create.status_code == 200
    payload = create.json()

    batch_id = payload["batch_id"]
    job_id = payload["jobs"][0]["job_id"]
    current_job_dir = Path(storage_module.job_dir(batch_id, job_id))
    (current_job_dir / "result.txt").write_text("hola", encoding="utf-8")
    (current_job_dir / "result.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")

    response = client.get(f"/batches/{batch_id}/download?format=all")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    zipped = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(zipped.namelist()) == sorted([f"{job_id}/result.srt", f"{job_id}/result.txt"])


def test_download_batch_results_filtered_format(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt"), ("export_formats", "srt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    job_id = payload["jobs"][0]["job_id"]
    current_job_dir = Path(storage_module.job_dir(batch_id, job_id))
    (current_job_dir / "result.txt").write_text("hola", encoding="utf-8")
    (current_job_dir / "result.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")

    response = client.get(f"/batches/{batch_id}/download?format=txt")
    assert response.status_code == 200

    zipped = zipfile.ZipFile(io.BytesIO(response.content))
    assert zipped.namelist() == [f"{job_id}/result.txt"]


def test_download_batch_results_404_when_no_files(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    batch_id = create.json()["batch_id"]

    response = client.get(f"/batches/{batch_id}/download?format=txt")
    assert response.status_code == 404


def test_download_batch_combined_txt(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    job_id = payload["jobs"][0]["job_id"]
    current_job_dir = Path(storage_module.job_dir(batch_id, job_id))
    (current_job_dir / "result.txt").write_text("hola mundo", encoding="utf-8")

    response = client.get(f"/batches/{batch_id}/download/txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert f"## {job_id}" in response.text
    assert "status: queued" in response.text
    assert "process_time_seconds:" in response.text
    assert "hola mundo" in response.text


def test_download_batch_combined_txt_404_when_no_txt(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    batch_id = create.json()["batch_id"]

    response = client.get(f"/batches/{batch_id}/download/txt")
    assert response.status_code == 404


def test_download_batch_combined_txt_with_options(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    job_id = payload["jobs"][0]["job_id"]
    current_job_dir = Path(storage_module.job_dir(batch_id, job_id))
    (current_job_dir / "result.txt").write_text("texto combinado", encoding="utf-8")

    response = client.get(
        f"/batches/{batch_id}/download/txt?label=filename&include_timestamps=true&separator=blank"
    )
    assert response.status_code == 200
    assert "## audio1.wav" in response.text
    assert "status: queued" in response.text
    assert "process_time_seconds:" in response.text
    assert "created_at:" in response.text
    assert "finished_at:" in response.text
    assert "texto combinado" in response.text


def test_download_batch_combined_txt_without_metrics(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    job_id = payload["jobs"][0]["job_id"]
    current_job_dir = Path(storage_module.job_dir(batch_id, job_id))
    (current_job_dir / "result.txt").write_text("solo texto", encoding="utf-8")

    response = client.get(f"/batches/{batch_id}/download/txt?include_metrics=false")
    assert response.status_code == 200
    assert f"## {job_id}" in response.text
    assert "status:" not in response.text
    assert "process_time_seconds:" not in response.text
    assert "solo texto" in response.text


def test_download_batch_combined_txt_include_empty_jobs(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    response = client.get(f"/batches/{batch_id}/download/txt?include_empty_jobs=true")

    assert response.status_code == 200
    assert "[sin resultado txt para este job]" in response.text


def test_download_batch_combined_txt_custom_empty_placeholder(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    payload = create.json()

    batch_id = payload["batch_id"]
    response = client.get(
        f"/batches/{batch_id}/download/txt?include_empty_jobs=true&empty_placeholder=sin+transcripcion"
    )

    assert response.status_code == 200
    assert "sin transcripcion" in response.text


def test_download_batch_combined_txt_sanitizes_empty_placeholder(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    batch_id = create.json()["batch_id"]

    response = client.get(
        f"/batches/{batch_id}/download/txt?include_empty_jobs=true&empty_placeholder=linea1%0Alinea2+++fin"
    )

    assert response.status_code == 200
    assert "linea1 linea2 fin" in response.text


def test_download_batch_combined_txt_caps_empty_placeholder_length(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    create = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    )
    batch_id = create.json()["batch_id"]

    long_placeholder = "a" * 250
    response = client.get(
        f"/batches/{batch_id}/download/txt?include_empty_jobs=true&empty_placeholder={long_placeholder}"
    )

    assert response.status_code == 200
    assert ("a" * 200) in response.text
    assert ("a" * 201) not in response.text


def test_create_batch_group_and_get_status(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    first = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()
    second = client.post(
        "/transcribe/batch",
        files=[("files", ("audio2.wav", b"fake-audio-2", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()

    group_response = client.post(
        "/batch-groups",
        json={"batch_ids": [first["batch_id"], second["batch_id"]], "name": "grupo-prueba"},
    )
    assert group_response.status_code == 200
    group_payload = group_response.json()
    assert group_payload["total_batches"] == 2

    group_id = group_payload["group_id"]
    status_response = client.get(f"/batch-groups/{group_id}")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["group_id"] == group_id
    assert status_payload["total_batches"] == 2
    assert status_payload["total_jobs"] == 2
    assert len(status_payload["batches"]) == 2


def test_create_batch_group_404_when_batch_missing(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    client = TestClient(main_module.app)

    response = client.post("/batch-groups", json={"batch_ids": ["inexistente"]})
    assert response.status_code == 404


def test_download_batch_group_results_as_zip(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    first = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()
    second = client.post(
        "/transcribe/batch",
        files=[("files", ("audio2.wav", b"fake-audio-2", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()

    first_batch_id = first["batch_id"]
    first_job_id = first["jobs"][0]["job_id"]
    second_batch_id = second["batch_id"]
    second_job_id = second["jobs"][0]["job_id"]

    Path(storage_module.job_dir(first_batch_id, first_job_id), "result.txt").write_text("uno", encoding="utf-8")
    Path(storage_module.job_dir(second_batch_id, second_job_id), "result.txt").write_text("dos", encoding="utf-8")

    group_id = client.post(
        "/batch-groups",
        json={"batch_ids": [first_batch_id, second_batch_id]},
    ).json()["group_id"]

    response = client.get(f"/batch-groups/{group_id}/download?format=txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    zipped = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(zipped.namelist()) == sorted(
        [
            f"{first_batch_id}/{first_job_id}/result.txt",
            f"{second_batch_id}/{second_job_id}/result.txt",
        ]
    )


def test_download_batch_group_combined_txt(tmp_path, monkeypatch) -> None:
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "enqueue_transcription_job", lambda **kwargs: None)

    client = TestClient(main_module.app)
    first = client.post(
        "/transcribe/batch",
        files=[("files", ("audio1.wav", b"fake-audio-1", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()
    second = client.post(
        "/transcribe/batch",
        files=[("files", ("audio2.wav", b"fake-audio-2", "audio/wav"))],
        data=[("export_formats", "txt")],
    ).json()

    first_batch_id = first["batch_id"]
    first_job_id = first["jobs"][0]["job_id"]
    second_batch_id = second["batch_id"]
    second_job_id = second["jobs"][0]["job_id"]

    Path(storage_module.job_dir(first_batch_id, first_job_id), "result.txt").write_text("texto uno", encoding="utf-8")
    Path(storage_module.job_dir(second_batch_id, second_job_id), "result.txt").write_text("texto dos", encoding="utf-8")

    group_id = client.post(
        "/batch-groups",
        json={"batch_ids": [first_batch_id, second_batch_id]},
    ).json()["group_id"]

    response = client.get(f"/batch-groups/{group_id}/download/txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert f"## {first_batch_id}/{first_job_id}" in response.text
    assert f"## {second_batch_id}/{second_job_id}" in response.text
    assert "texto uno" in response.text
    assert "texto dos" in response.text
