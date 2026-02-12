from pydantic import BaseModel, Field


class SegmentResponse(BaseModel):
    start: float = Field(..., description="Segment start timestamp in seconds")
    end: float = Field(..., description="Segment end timestamp in seconds")
    text: str = Field(..., description="Transcribed text")


class TranscriptionResponse(BaseModel):
    language: str = Field(..., description="Detected or selected language")
    duration: float = Field(..., description="Audio duration in seconds")
    text: str = Field(..., description="Full transcription")
    segments: list[SegmentResponse] = Field(..., description="Transcription segments")
