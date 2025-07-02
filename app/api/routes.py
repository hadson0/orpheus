"""
API routes for Spotify Voice Bridge.

This module defines all HTTP endpoints for the API, handling
QR code generation, OAuth callbacks, voice commands, and token refresh.
"""

import io
import string
import random
from flask import (
    Blueprint,
    request,
    jsonify,
    Response,
    render_template_string,
    current_app,
    redirect,
)
import qrcode
from app.api import api_bp
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
from app.api.models import ShortURL
from app import db

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Spotify Voice Bridge - Success</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #1DB954;
            color: white;
        }
        .container {
            text-align: center;
            padding: 2rem;
            background-color: rgba(0, 0, 0, 0.2);
            border-radius: 10px;
        }
        .icon {
            font-size: 4rem;
            margin-bottom: 1rem;
        }
        h1 {
            margin: 0 0 1rem 0;
        }
        p {
            margin: 0;
            opacity: 0.9;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Success!</h1>
        <p>Your device has been connected to Spotify.</p>
        <p>You can now close this window.</p>
    </div>
</body>
</html>
"""

ERROR_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Spotify Voice Bridge - Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #E22134;
            color: white;
        }
        .container {
            text-align: center;
            padding: 2rem;
            background-color: rgba(0, 0, 0, 0.2);
            border-radius: 10px;
            max-width: 500px;
        }
        .icon {
            font-size: 4rem;
            margin-bottom: 1rem;
        }
        h1 {
            margin: 0 0 1rem 0;
        }
        p {
            margin: 0 0 1rem 0;
            opacity: 0.9;
        }
        .error-details {
            background-color: rgba(0, 0, 0, 0.2);
            padding: 1rem;
            border-radius: 5px;
            font-size: 0.9rem;
            text-align: left;
            word-break: break-word;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✗</div>
        <h1>Authentication Failed</h1>
        <p>There was an error connecting your device to Spotify.</p>
        <div class="error-details">{{ error_message }}</div>
    </div>
</body>
</html>
"""


def generate_code(length=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@api_bp.route("/qr/<string:device_id>", methods=["GET"])
def generate_qr_code(device_id: str) -> Response:
    """
    Generate QR code for device authentication.
    ---
    parameters:
      - name: device_id
        in: path
        type: string
        required: true
        description: Device identifier
    responses:
      200:
        description: PNG image with QR code
        content:
          image/png:
            schema:
              type: string
              format: binary
      400:
        description: Invalid device ID
      500:
        description: Internal server error
    """
    try:
        if not device_id or len(device_id) > 255:
            return (
                jsonify(
                    {
                        "error": "Invalid device ID",
                        "message": "Device ID must be between 1 and 255 characters",
                    }
                ),
                400,
            )

        auth_url = generate_spotify_auth_url(device_id)
        current_app.logger.info(f"Generated Auth URL: {auth_url}")

        # --- Always shorten the URL for QR code ---
        # Check if already shortened
        short = ShortURL.query.filter_by(long_url=auth_url).first()
        if not short:
            # Generate a unique code
            for _ in range(5):
                code = generate_code()
                if not ShortURL.query.filter_by(code=code).first():
                    break
            else:
                return jsonify({"error": "Could not generate unique code"}), 500

            short = ShortURL(code=code, long_url=auth_url)
            db.session.add(short)
            db.session.commit()
            current_app.logger.info(f"Shortened URL created: {short.code}")

        short_url = request.url_root.rstrip("/") + "/u/" + short.code
        current_app.logger.info(f"QR code will encode: {short_url}")

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=2,
            border=1,
        )
        qr.add_data(short_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        return Response(
            img_buffer.getvalue(),
            mimetype="image/png",
            headers={
                "Content-Disposition": f'inline; filename="spotify_auth_{device_id}.png"',
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    except ValueError as e:
        current_app.logger.error(f"Configuration error generating QR code: {str(e)}")
        return jsonify({"error": "Configuration Error", "message": str(e)}), 500

    except Exception as e:
        current_app.logger.error(f"Error generating QR code: {str(e)}")
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "Failed to generate QR code",
                }
            ),
            500,
        )


@api_bp.route("/auth/callback", methods=["GET"])
def auth_callback() -> Response:
    """
    Handle Spotify OAuth2 callback.
    ---
    parameters:
      - name: code
        in: query
        type: string
        required: false
        description: Authorization code from Spotify
      - name: state
        in: query
        type: string
        required: false
        description: State parameter for CSRF protection
      - name: error
        in: query
        type: string
        required: false
        description: Error message from Spotify
    responses:
      200:
        description: Success HTML page
      400:
        description: Error HTML page
      500:
        description: Internal server error
    """
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        error_description = request.args.get("error_description", "Unknown error")
        current_app.logger.error(f"Spotify auth error: {error} - {error_description}")
        return Response(
            render_template_string(
                ERROR_HTML, error_message=f"{error}: {error_description}"
            ),
            status=400,
            mimetype="text/html",
        )

    if not code or not state:
        current_app.logger.error("Missing code or state in callback")
        return Response(
            render_template_string(
                ERROR_HTML, error_message="Missing required parameters"
            ),
            status=400,
            mimetype="text/html",
        )

    try:
        success, message = process_callback(state, code)

        if success:
            current_app.logger.info(f"Successfully processed callback: {message}")
            return Response(SUCCESS_HTML, status=200, mimetype="text/html")
        else:
            return Response(
                render_template_string(ERROR_HTML, error_message=message),
                status=400,
                mimetype="text/html",
            )

    except ValueError as e:
        current_app.logger.error(f"Callback processing error: {str(e)}")
        return Response(
            render_template_string(ERROR_HTML, error_message=str(e)),
            status=400,
            mimetype="text/html",
        )

    except Exception as e:
        current_app.logger.error(f"Unexpected callback error: {str(e)}")
        return Response(
            render_template_string(
                ERROR_HTML, error_message="An unexpected error occurred"
            ),
            status=500,
            mimetype="text/html",
        )


@api_bp.route("/command", methods=["POST"])
def process_command() -> Response:
    """
    Process voice command from device.
    ---
    consumes:
      - multipart/form-data
    parameters:
      - name: device_id
        in: formData
        type: string
        required: true
        description: Device identifier
      - name: audio
        in: formData
        type: file
        required: true
        description: Audio file with voice command
    responses:
      200:
        description: Command processed
      400:
        description: Bad request
      401:
        description: Unauthorized
      500:
        description: Internal server error
    """
    try:
        device_id = request.form.get("device_id")
        if not device_id:
            return (
                jsonify({"error": "Bad Request", "message": "device_id is required"}),
                400,
            )

        if "audio" not in request.files:
            return (
                jsonify({"error": "Bad Request", "message": "audio file is required"}),
                400,
            )

        audio_file = request.files["audio"]
        if audio_file.filename == "":
            return (
                jsonify({"error": "Bad Request", "message": "No audio file selected"}),
                400,
            )

        if not validate_audio_format(audio_file):
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "Unsupported audio format. Supported: mp3, mp4, mpeg, mpga, m4a, wav, webm",
                    }
                ),
                400,
            )

        access_token = get_valid_token(device_id)
        if not access_token:
            return (
                jsonify(
                    {
                        "error": "Unauthorized",
                        "message": "Device not authenticated or token refresh failed",
                        "device_id": device_id,
                    }
                ),
                401,
            )

        try:
            transcribed_text = transcribe_audio(audio_file)
        except ValueError as e:
            return jsonify({"error": "Transcription Error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"Transcription failed: {str(e)}")
            return (
                jsonify(
                    {
                        "error": "Transcription Failed",
                        "message": "Failed to transcribe audio",
                    }
                ),
                500,
            )

        command = parse_command(transcribed_text)

        if not command:
            return (
                jsonify(
                    {
                        "success": True,
                        "transcribed_text": transcribed_text,
                        "command": None,
                        "message": "No command detected in audio",
                        "action_taken": False,
                    }
                ),
                200,
            )

        result = execute_command(command, transcribed_text, device_id)

        response_data = {
            "success": result["success"],
            "transcribed_text": transcribed_text,
            "command": command,
            "message": result["message"],
            "action_taken": result["success"],
        }

        if "error" in result:
            response_data["error"] = result["error"]

        if "details" in result:
            response_data["details"] = result["details"]

        status_code = 200 if result["success"] else 400

        current_app.logger.info(
            f"Command processed - Device: {device_id}, "
            f"Text: '{transcribed_text}', Command: {command}, "
            f"Success: {result['success']}"
        )

        return jsonify(response_data), status_code

    except Exception as e:
        current_app.logger.error(f"Unexpected error processing command: {str(e)}")
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                }
            ),
            500,
        )


@api_bp.route("/refresh", methods=["POST"])
def refresh_device_token() -> Response:
    """
    Refresh device Spotify token.
    ---
    consumes:
      - application/json
    parameters:
      - name: device_id
        in: body
        required: true
        schema:
          type: object
          properties:
            device_id:
              type: string
              description: Device identifier
    responses:
      200:
        description: Token refreshed
      400:
        description: Bad request or refresh failed
      500:
        description: Internal server error
    """
    try:
        if not request.is_json:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "Content-Type must be application/json",
                    }
                ),
                400,
            )
        data = request.get_json()
        device_id = data.get("device_id") if data else None

        if not device_id:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "message": "device_id is required in JSON body",
                    }
                ),
                400,
            )

        success = refresh_token_for_device(device_id)

        if success:
            current_app.logger.info(
                f"Successfully refreshed token for device: {device_id}"
            )
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Token refreshed successfully for device {device_id}",
                        "device_id": device_id,
                    }
                ),
                200,
            )
        else:
            current_app.logger.warning(
                f"Failed to refresh token for device: {device_id}"
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"Failed to refresh token for device {device_id}",
                        "device_id": device_id,
                        "error": "refresh_failed",
                    }
                ),
                400,
            )

    except Exception as e:
        current_app.logger.error(f"Unexpected error refreshing token: {str(e)}")
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                }
            ),
            500,
        )


@api_bp.route("/u/<string:code>", methods=["GET"])
def redirect_short_url(code):
    """
    Redirect to long URL from short code.
    ---
    parameters:
      - name: code
        in: path
        type: string
        required: true
        description: Short URL code
    responses:
      302:
        description: Redirect to long URL
      404:
        description: Code not found
    """
    short = ShortURL.query.filter_by(code=code).first()
    if not short:
        return jsonify({"error": "Not found"}), 404
    return redirect(short.long_url)


# Additional utility endpoints (optional)


@api_bp.route("/health", methods=["GET"])
def health_check() -> Response:
    """
    Health check endpoint.
    ---
    responses:
      200:
        description: Service is healthy
    """
    return (
        jsonify(
            {
                "status": "healthy",
                "service": "Spotify Voice Bridge API",
                "version": "1.0.0",
            }
        ),
        200,
    )


@api_bp.route("/device/<string:device_id>/status", methods=["GET"])
def device_status(device_id: str) -> Response:
    """
    Get device authentication status.
    ---
    parameters:
      - name: device_id
        in: path
        type: string
        required: true
        description: Device identifier
    responses:
      200:
        description: Device status
      404:
        description: Device not found
      500:
        description: Internal server error
    """
    try:
        from app.services.auth_service import get_device_status

        status = get_device_status(device_id)

        if not status["exists"]:
            return (
                jsonify(
                    {
                        "error": "Not Found",
                        "message": f"Device {device_id} not found",
                        "device_id": device_id,
                    }
                ),
                404,
            )

        return jsonify(status), 200

    except Exception as e:
        current_app.logger.error(f"Error getting device status: {str(e)}")
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "Failed to get device status",
                }
            ),
            500,
        )


@api_bp.route("/", methods=["GET"])
def api_info() -> Response:
    """
    API information and available endpoints.
    ---
    responses:
      200:
        description: API info and endpoints
    """
    return (
        jsonify(
            {
                "service": "Spotify Voice Bridge API",
                "version": "1.0.0",
                "endpoints": {
                    "qr_code": {
                        "method": "GET",
                        "path": "/qr/<device_id>",
                        "description": "Generate QR code for device authentication",
                    },
                    "auth_callback": {
                        "method": "GET",
                        "path": "/auth/callback",
                        "description": "OAuth2 callback endpoint (used by Spotify)",
                    },
                    "command": {
                        "method": "POST",
                        "path": "/command",
                        "description": "Process voice command from device",
                    },
                    "refresh": {
                        "method": "POST",
                        "path": "/refresh",
                        "description": "Manually refresh device token",
                    },
                    "health": {
                        "method": "GET",
                        "path": "/health",
                        "description": "Health check endpoint",
                    },
                    "device_status": {
                        "method": "GET",
                        "path": "/device/<device_id>/status",
                        "description": "Get device authentication status",
                    },
                },
            }
        ),
        200,
    )
