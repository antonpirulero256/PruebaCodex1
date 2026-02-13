from app.utils.subtitles import to_srt, to_vtt


def test_to_srt_formats_segment_with_index_and_comma_timestamps() -> None:
    segments = [{"start": 0.0, "end": 1.25, "text": "Hola mundo"}]

    result = to_srt(segments)

    expected = "1\n00:00:00,000 --> 00:00:01,250\nHola mundo\n"
    assert result == expected


def test_to_vtt_formats_header_and_dot_timestamps() -> None:
    segments = [{"start": 2.1, "end": 3.45, "text": "Testing VTT"}]

    result = to_vtt(segments)

    expected = "WEBVTT\n\n00:00:02.100 --> 00:00:03.450\nTesting VTT\n"
    assert result == expected
