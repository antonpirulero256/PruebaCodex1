from __future__ import annotations

import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from app.config import COMPUTE_TYPE, DEVICE, MODEL_SIZE


class Transcriber:
    def __init__(self, model_size: str, compute_type: str, device: str) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        beam_size: int,
        vad_filter: bool,
    ) -> dict[str, Any]:
        normalized_path = self._normalize_audio(audio_path)
        try:
            segments, info = self._model.transcribe(
                str(normalized_path),
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                word_timestamps=False,
            )
            parsed_segments = [
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": segment.text.strip(),
                }
                for segment in segments
            ]
            full_text = " ".join(seg["text"] for seg in parsed_segments if seg["text"]).strip()
            return {
                "language": info.language,
                "duration": round(info.duration, 3),
                "text": full_text,
                "segments": parsed_segments,
            }
        finally:
            if normalized_path != audio_path and normalized_path.exists():
                normalized_path.unlink()

    def _normalize_audio(self, audio_path: Path) -> Path:
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            return audio_path

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            output_path = Path(temp_file.name)

        command = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            if output_path.exists():
                output_path.unlink()
            return audio_path

        return output_path


@lru_cache(maxsize=1)
def get_transcriber() -> Transcriber:
    return Transcriber(model_size=MODEL_SIZE, compute_type=COMPUTE_TYPE, device=DEVICE)
