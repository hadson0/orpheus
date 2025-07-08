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
import wave


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


def validate_audio_format(audio_file) -> bool:
    """
    Validate if the uploaded audio file is in a supported format.
    Supported: mp3, mp4, mpeg, mpga, m4a, wav, webm, pcm
    """
    allowed_extensions = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "pcm"}
    filename = audio_file.filename.lower()
    return any(filename.endswith(f".{ext}") for ext in allowed_extensions)


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


def convert_pcm_to_wav(pcm_file, sample_rate=16000, channels=1, sample_width=2):
    """
    Converts a PCM file-like object to a WAV file-like object.
    Assumes 16-bit PCM by default.
    """
    pcm_file.seek(0)
    pcm_data = pcm_file.read()
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    wav_buffer.seek(0)
    return wav_buffer
