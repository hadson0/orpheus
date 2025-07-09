from __future__ import annotations

import io
import random
import string
from http import HTTPStatus
from typing import Dict, Any, Optional

import qrcode
from flask import (
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    make_response,
)

from app import db
from app.api import api_bp
from app.api.models import ShortURL
from app.services import (
    generate_spotify_auth_url,
    process_callback,
    refresh_token_for_device,
    get_valid_token,
    transcribe_audio,
    parse_command,
    execute_command,
)
from app.services.whisper_service import validate_audio_format


def _json(data: Dict[str, Any], status: HTTPStatus) -> Response:
    """Return JSON response with status."""
    return make_response(jsonify(data), status)


def _html(html: str, status: HTTPStatus) -> Response:
    """Return HTML response with status."""
    return Response(html, status=status, mimetype="text/html")


def _render_error_html(
    msg: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST
) -> Response:
    html_content = render_template("error.html", error_message=msg)
    return _html(html_content, status)


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _shorten_url(long_url: str) -> str:
    """Return a short URL, creating it if needed."""
    short: Optional[ShortURL] = ShortURL.query.filter_by(long_url=long_url).first()
    if short:
        return request.url_root.rstrip("/") + "/u/" + short.code

    for _ in range(5):
        code = _generate_code()
        if not ShortURL.query.filter_by(code=code).first():
            short = ShortURL(code=code, long_url=long_url)
            db.session.add(short)
            db.session.commit()
            return request.url_root.rstrip("/") + "/u/" + code

    raise RuntimeError("Could not generate unique code")


def _create_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=2,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


@api_bp.route("/qr/<string:device_id>", methods=["GET"])
def generate_qr_code(device_id: str) -> Response:
    """Return PNG QR code for the device's Spotify auth URL."""
    if not (1 <= len(device_id) <= 255):
        return _json(
            {"error": "Invalid device ID", "message": "1-255 chars required"},
            HTTPStatus.BAD_REQUEST,
        )

    try:
        auth_url = generate_spotify_auth_url(device_id)
        short_url = _shorten_url(auth_url)
        png_bytes = _create_qr_png(short_url)

        return Response(
            png_bytes,
            mimetype="image/png",
            headers={
                "Content-Disposition": f'inline; filename="spotify_auth_{device_id}.png"',
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as exc:
        current_app.logger.exception("QR generation failed – %s", exc)
        return _json(
            {"error": "Internal Server Error", "message": "Failed to generate QR"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@api_bp.route("/auth/callback", methods=["GET"])
def auth_callback() -> Response:
    code, state, err = (
        request.args.get("code"),
        request.args.get("state"),
        request.args.get("error"),
    )

    if err:
        desc = request.args.get("error_description", "Unknown error")
        current_app.logger.error("Spotify auth error: %s – %s", err, desc)
        return _render_error_html(f"{err}: {desc}", HTTPStatus.BAD_REQUEST)

    if not code or not state:
        return _render_error_html("Missing required parameters", HTTPStatus.BAD_REQUEST)

    try:
        success, msg = process_callback(state, code)
        if success:
            html_content = render_template("success.html")
            status = HTTPStatus.OK
        else:
            html_content = render_template("error.html", error_message=msg)
            status = HTTPStatus.BAD_REQUEST
        return _html(html_content, status)

    except ValueError as exc:
        return _render_error_html(str(exc), HTTPStatus.BAD_REQUEST)
    except Exception as exc:
        current_app.logger.exception("Unexpected callback error – %s", exc)
        return _render_error_html(
            "An unexpected error occurred", HTTPStatus.INTERNAL_SERVER_ERROR
        )


@api_bp.route("/command", methods=["POST"])
def process_command() -> Response:
    device_id = request.form.get("device_id")
    if not device_id:
        return _json({"error": "device_id is required"}, HTTPStatus.BAD_REQUEST)

    audio = request.files.get("audio")
    if not audio or audio.filename == "":
        return _json({"error": "audio file is required"}, HTTPStatus.BAD_REQUEST)

    if not validate_audio_format(audio):
        return _json(
            {
                "error": "Unsupported audio format",
                "supported": "mp3, mp4, mpeg, mpga, m4a, wav, webm",
            },
            HTTPStatus.BAD_REQUEST,
        )

    access_token = get_valid_token(device_id)
    if not access_token:
        return _json(
            {
                "error": "Unauthorized",
                "message": "Device not authenticated or token refresh failed",
                "device_id": device_id,
            },
            HTTPStatus.UNAUTHORIZED,
        )

    try:
        transcribed = transcribe_audio(audio)
    except ValueError as e:
        return _json(
            {"error": "Transcription Error", "message": str(e)}, HTTPStatus.BAD_REQUEST
        )
    except Exception as exc:
        current_app.logger.exception("Transcription failed – %s", exc)
        return _json(
            {"error": "Transcription Failed", "message": "Failed to transcribe audio"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    command = parse_command(transcribed)
    if not command:
        return _json(
            {
                "success": True,
                "transcribed_text": transcribed,
                "command": None,
                "message": "No command detected in audio",
                "action_taken": False,
            },
            HTTPStatus.OK,
        )

    cmd_name, name = command
    result = execute_command(cmd_name, name, device_id)
    current_app.logger.info(
        "Command processed – Device:%s | '%s' → %s | ok=%s",
        device_id,
        transcribed,
        command,
        result["success"],
    )

    status = HTTPStatus.OK if result["success"] else HTTPStatus.BAD_REQUEST
    payload = {
        "success": result["success"],
        "transcribed_text": transcribed,
        "command": command,
        "message": result["message"],
        "action_taken": result["success"],
        **{k: v for k, v in result.items() if k in {"error", "details"}},
    }
    return _json(payload, status)


@api_bp.route("/refresh", methods=["POST"])
def refresh_device_token() -> Response:
    if not request.is_json:
        return _json(
            {"error": "Content-Type must be application/json"}, HTTPStatus.BAD_REQUEST
        )

    device_id = (request.get_json() or {}).get("device_id")
    if not device_id:
        return _json({"error": "device_id is required"}, HTTPStatus.BAD_REQUEST)

    try:
        if refresh_token_for_device(device_id):
            return _json(
                {
                    "success": True,
                    "message": f"Token refreshed for device {device_id}",
                    "device_id": device_id,
                },
                HTTPStatus.OK,
            )
        return _json(
            {
                "success": False,
                "message": f"Failed to refresh token for device {device_id}",
                "device_id": device_id,
                "error": "refresh_failed",
            },
            HTTPStatus.BAD_REQUEST,
        )
    except Exception as exc:
        current_app.logger.exception("Unexpected error refreshing token – %s", exc)
        return _json(
            {
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
            },
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@api_bp.route("/u/<string:code>", methods=["GET"])
def redirect_short_url(code: str) -> Response:
    short = ShortURL.query.filter_by(code=code).first()
    return (
        redirect(short.long_url)
        if short
        else _json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
    )


@api_bp.route("/health", methods=["GET"])
def health_check() -> Response:
    return _json(
        {
            "status": "healthy",
            "service": "Spotify Voice Bridge API",
            "version": "1.0.0",
        },
        HTTPStatus.OK,
    )


@api_bp.route("/device/<string:device_id>/status", methods=["GET"])
def device_status(device_id: str) -> Response:
    from app.api.models import DeviceAuth

    try:
        device = DeviceAuth.get_by_device_id(device_id)
        if not device:
            return _json(
                {
                    "device_id": device_id,
                    "registered": False,
                    "authenticated": False,
                    "message": "Device not found",
                },
                HTTPStatus.NOT_FOUND,
            )

        return _json(
            {
                "device_id": device_id,
                "registered": True,
                "authenticated": not device.is_token_expired
                and device.has_required_scopes,
                "expires_at": (
                    device.expires_at.isoformat() if device.expires_at else None
                ),
                "last_updated": (
                    device.updated_at.isoformat() if device.updated_at else None
                ),
            },
            HTTPStatus.OK,
        )
    except Exception as exc:
        current_app.logger.exception("Device status error – %s", exc)
        return _json(
            {
                "error": "Internal Server Error",
                "message": "Failed to check device status",
            },
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@api_bp.route("/", methods=["GET"])
def api_info() -> Response:
    return _json(
        {
            "service": "Spotify Voice Bridge API",
            "version": "1.0.0",
            "endpoints": {
                "qr_code": {
                    "method": "GET",
                    "path": "/qr/<device_id>",
                    "description": "Generate QR code",
                },
                "auth_cb": {
                    "method": "GET",
                    "path": "/auth/callback",
                    "description": "OAuth2 callback",
                },
                "command": {
                    "method": "POST",
                    "path": "/command",
                    "description": "Process voice command",
                },
                "refresh": {
                    "method": "POST",
                    "path": "/refresh",
                    "description": "Manually refresh token",
                },
                "health": {
                    "method": "GET",
                    "path": "/health",
                    "description": "Health check",
                },
                "dev_stat": {
                    "method": "GET",
                    "path": "/device/<device_id>/status",
                    "description": "Device status",
                },
            },
        },
        HTTPStatus.OK,
    )
