from __future__ import annotations

import app.queueing as queueing


def test_enqueue_transcription_job_uses_enqueue_call(monkeypatch) -> None:
    captured: dict = {}

    class FakeQueue:
        def enqueue_call(self, **kwargs):
            captured.update(kwargs)
            return "ok"

    monkeypatch.setattr(queueing, "get_queue", lambda: FakeQueue())

    result = queueing.enqueue_transcription_job(
        batch_id="batch-1",
        job_id="job-1",
        input_path="/tmp/input.wav",
        language="es",
        beam_size=5,
        vad_filter=True,
        export_formats=["json", "srt"],
    )

    assert result == "ok"
    assert captured["func"] == "app.worker.process_transcription_job"
    assert captured["job_id"] == "job-1"
    assert captured["kwargs"]["job_id"] == "job-1"
    assert captured["kwargs"]["batch_id"] == "batch-1"
