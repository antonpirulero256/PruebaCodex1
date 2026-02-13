from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
import app.storage as storage_module


def _patch_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "BATCHES_ROOT", tmp_path / "batches")
    monkeypatch.setattr(storage_module, "JOBS_INDEX_ROOT", tmp_path / "jobs")
    storage_module.ensure_storage_dirs()


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
