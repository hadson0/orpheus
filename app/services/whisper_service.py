"""
OpenAI Whisper service for audio transcription.

This module handles audio file transcription using the OpenAI Whisper API
to convert voice commands into text.
"""

import io
import logging
from typing import Union, BinaryIO
from werkzeug.datastructures import FileStorage
from flask import current_app
import openai
import requests


def transcribe_audio(audio_file: Union[FileStorage, BinaryIO]) -> str:
    """
    Transcribe audio file to text using OpenAI Whisper API.
    """
    import io

    api_key = current_app.config.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    openai.api_key = api_key

    if not audio_file:
        raise ValueError("No audio file provided")

    try:
        if isinstance(audio_file, FileStorage):
            filename = audio_file.filename or "audio.wav"
            audio_file.stream.seek(0)
            file_bytes = audio_file.stream.read()
        else:
            filename = getattr(audio_file, "name", "audio.wav")
            audio_file.seek(0)
            file_bytes = audio_file.read()

        file_data = io.BytesIO(file_bytes)
        file_data.name = filename

    except Exception as e:
        current_app.logger.error(f"Failed to read audio file: {str(e)}")
        raise ValueError(f"Invalid audio file: {str(e)}")

    current_app.logger.info(f"Attempting to transcribe audio file: {filename}")

    try:
        response = openai.audio.transcriptions.create(
            model=current_app.config.get("OPENAI_MODEL", "whisper-1"),
            file=file_data,
            response_format="text",
            language=None,
            temperature=0,
        )
        transcribed_text = (
            response.strip() if isinstance(response, str) else str(response).strip()
        )

        if not transcribed_text:
            current_app.logger.warning("Transcription returned empty text")
            return ""

        current_app.logger.info(
            f"Successfully transcribed: '{transcribed_text[:50]}...'"
        )
        return transcribed_text

    except openai.OpenAIError as e:
        current_app.logger.error(f"OpenAI API error: {str(e)}")
        raise requests.RequestException(f"OpenAI API error: {str(e)}")
    except Exception as e:
        current_app.logger.error(f"Unexpected error during transcription: {str(e)}")
        raise Exception(f"Transcription failed: {str(e)}")
    finally:
        if hasattr(audio_file, "seek"):
            try:
                audio_file.seek(0)
            except:
                pass


def validate_audio_format(audio_file: FileStorage) -> bool:
    """
    Validate if the audio file format is supported by Whisper.

    Supported formats: mp3, mp4, mpeg, mpga, m4a, wav, webm

    Args:
        audio_file: Flask FileStorage object.

    Returns:
        bool: True if format is supported, False otherwise.
    """
    if not audio_file or not audio_file.filename:
        return False

    supported_extensions = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
    supported_mimetypes = {
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/m4a",
    }

    filename = audio_file.filename.lower()
    extension = "." + filename.split(".")[-1] if "." in filename else ""

    mimetype = audio_file.mimetype.lower() if audio_file.mimetype else ""

    is_valid = extension in supported_extensions or mimetype in supported_mimetypes

    if not is_valid:
        current_app.logger.warning(
            f"Unsupported audio format: {filename} (mimetype: {mimetype})"
        )

    return is_valid


def get_audio_duration(audio_file: Union[FileStorage, BinaryIO]) -> float:
    """
    Get approximate duration of audio file in seconds.

    Note: This is a simplified implementation. For production,
    consider using libraries like pydub or mutagen for accurate duration.

    Args:
        audio_file: Audio file to analyze.

    Returns:
        float: Approximate duration in seconds (0.0 if unable to determine).
    """
    try:
        # Reset position
        if hasattr(audio_file, "seek"):
            audio_file.seek(0)

        # Get file size
        if hasattr(audio_file, "content_length"):
            file_size = audio_file.content_length
        else:
            # Try to get size by seeking to end
            current_pos = audio_file.tell() if hasattr(audio_file, "tell") else 0
            audio_file.seek(0, 2)  # Seek to end
            file_size = audio_file.tell()
            audio_file.seek(current_pos)  # Reset position

        # Assuming ~128 kbps bitrate (16 KB/s)
        estimated_duration = file_size / (16 * 1024)

        return max(0.0, estimated_duration)

    except Exception as e:
        current_app.logger.debug(f"Could not determine audio duration: {str(e)}")
        return 0.0


def preprocess_audio(audio_file: FileStorage) -> io.BytesIO:
    """
    Preprocess audio file for optimal Whisper performance.

    This is a placeholder for potential audio preprocessing like:
    - Resampling to 16kHz
    - Converting to mono
    - Normalizing audio levels

    Args:
        audio_file: Input audio file.

    Returns:
        io.BytesIO: Preprocessed audio data.
    """
    # For now, just return the original data
    data = audio_file.read()
    audio_file.seek(0)  # Reset for potential future reads

    return io.BytesIO(data)


def test_whisper_connection() -> bool:
    """
    Test connection to OpenAI Whisper API.

    Returns:
        bool: True if connection is successful.
    """
    try:
        api_key = current_app.config.get("OPENAI_API_KEY")
        if not api_key:
            return False

        openai.api_key = api_key

        models = openai.Model.list()

        whisper_available = any("whisper" in model.id.lower() for model in models.data)

        current_app.logger.info(
            f"Whisper API test successful. Whisper available: {whisper_available}"
        )
        return True

    except Exception as e:
        current_app.logger.error(f"Whisper API test failed: {str(e)}")
        return False
