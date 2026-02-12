from __future__ import annotations

from typing import Iterable


def _format_timestamp(seconds: float, decimal_separator: str = ",") -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02}:{minutes:02}:{secs:02}{decimal_separator}{millis:03}"


def to_srt(segments: Iterable[dict]) -> str:
    lines: list[str] = []
    for idx, segment in enumerate(segments, start=1):
        start = _format_timestamp(segment["start"], decimal_separator=",")
        end = _format_timestamp(segment["end"], decimal_separator=",")
        text = segment["text"].strip()
        lines.extend([str(idx), f"{start} --> {end}", text, ""])
    return "\n".join(lines).strip() + "\n"


def to_vtt(segments: Iterable[dict]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for segment in segments:
        start = _format_timestamp(segment["start"], decimal_separator=".")
        end = _format_timestamp(segment["end"], decimal_separator=".")
        text = segment["text"].strip()
        lines.extend([f"{start} --> {end}", text, ""])
    return "\n".join(lines).strip() + "\n"
