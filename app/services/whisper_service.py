from __future__ import annotations

import io
import wave
from typing import BinaryIO, Final, Optional, Union

import openai
import requests
from flask import current_app
from werkzeug.datastructures import FileStorage

SUPPORTED_EXTENSIONS: Final[set[str]] = {
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "m4a",
    "wav",
    "webm",
}


def _cfg(key: str, default=None):
    return current_app.config.get(key, default)


def _openai_api_key() -> str:
    key = _cfg("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not configured")
    openai.api_key = key
    return key


def _file_to_bytes(audio: Union[FileStorage, BinaryIO]) -> tuple[io.BytesIO, str]:
    """Return (BytesIO, filename) for OpenAI upload. Raise ValueError on error."""
    try:
        if isinstance(audio, FileStorage):
            filename = audio.filename or "audio.wav"
            audio.stream.seek(0)
            data = audio.stream.read()
        else:
            filename = getattr(audio, "name", "audio.wav")
            audio.seek(0)
            data = audio.read()

        buf = io.BytesIO(data)
        buf.name = filename
        return buf, filename
    except Exception as exc:
        current_app.logger.error("Failed reading audio file – %s", exc)
        raise ValueError(f"Invalid audio file: {exc}") from exc


def _log_success(text: str) -> None:
    current_app.logger.info("Successfully transcribed: %.50s…", text)


def transcribe_audio(audio_file: Union[FileStorage, BinaryIO]) -> str:
    """
    Transcribe speech to text using OpenAI Whisper.
    Raise ValueError for config/file errors, RequestException for API errors.
    """
    _openai_api_key()
    if not audio_file:
        raise ValueError("No audio file provided")

    file_data, filename = _file_to_bytes(audio_file)
    current_app.logger.info("Transcribing audio: %s", filename)

    try:
        response = openai.audio.transcriptions.create(
            model=_cfg("OPENAI_MODEL", "whisper-1"),
            file=file_data,
            response_format="text",
            language=None,
            temperature=0,
        )
        text = response.strip() if isinstance(response, str) else str(response).strip()
        _log_success(text or "<empty>")
        return text
    except openai.OpenAIError as exc:
        current_app.logger.error("OpenAI API error – %s", exc)
        raise requests.RequestException(f"OpenAI API error: {exc}") from exc
    except Exception as exc:
        current_app.logger.exception("Unexpected transcription error")
        raise RuntimeError(f"Transcription failed: {exc}") from exc
    finally:
        try:
            if hasattr(audio_file, "seek"):
                audio_file.seek(0)
        except Exception:
            pass


def validate_audio_format(audio_file: FileStorage) -> bool:
    """Return True if file extension is allowed."""
    return any(
        audio_file.filename.lower().endswith(f".{ext}") for ext in SUPPORTED_EXTENSIONS
    )


def get_audio_duration(audio_file: Union[FileStorage, BinaryIO]) -> float:
    """Estimate duration in seconds by file size (~128 kbps = 16 KB/s)."""
    try:
        if hasattr(audio_file, "seek"):
            audio_file.seek(0, 2)
            size = audio_file.tell()
            audio_file.seek(0)
        else:
            size = getattr(audio_file, "content_length", 0)
        return max(0.0, size / (16 * 1024))
    except Exception as exc:
        current_app.logger.debug("Could not estimate duration – %s", exc)
        return 0.0


def preprocess_audio(audio_file: FileStorage) -> io.BytesIO:
    """Return raw bytes in a BytesIO buffer (placeholder for future processing)."""
    data = audio_file.read()
    audio_file.seek(0)
    return io.BytesIO(data)


def test_whisper_connection() -> bool:
    """Return True if Whisper API is reachable."""
    try:
        _openai_api_key()
        models = openai.Model.list()
        available = any("whisper" in m.id.lower() for m in models.data)
        current_app.logger.info(
            "Whisper API reachable, whisper available=%s", available
        )
        return True
    except Exception as exc:
        current_app.logger.error("Whisper API test failed – %s", exc)
        return False
