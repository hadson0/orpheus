"""
Authentication service for Spotify OAuth2 flow.

This module handles the OAuth2 authentication flow with Spotify,
including URL generation, callback processing, and token management.
"""

import secrets
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from urllib.parse import urlencode
import requests
from flask import current_app
from app import db
from app.api.models import DeviceAuth


# {state: {'device_id': str, 'created_at': float}}
_auth_states: Dict[str, Dict[str, any]] = {}


def _cleanup_expired_states() -> None:
    """Remove expired states from temporary storage."""
    current_time = time.time()
    ttl = current_app.config.get("AUTH_STATE_TTL", 300)  # 5 minutes default

    expired_states = [
        state
        for state, data in _auth_states.items()
        if current_time - data["created_at"] > ttl
    ]

    for state in expired_states:
        del _auth_states[state]
        current_app.logger.debug(f"Cleaned up expired state: {state[:8]}...")


def _generate_state(device_id: str) -> str:
    """
    Generate a secure state parameter containing the device ID.

    Args:
        device_id: The device identifier to embed in the state.

    Returns:
        str: A secure random state string.
    """
    _cleanup_expired_states()

    state = secrets.token_urlsafe(4)

    _auth_states[state] = {"device_id": device_id, "created_at": time.time()}

    current_app.logger.info(f"Generated auth state for device {device_id}")
    return state


def _validate_state(state: str) -> Optional[str]:
    """
    Validate state parameter and extract device ID.

    Args:
        state: The state parameter from the callback.

    Returns:
        Optional[str]: The device ID if valid, None otherwise.
    """
    if not state or state not in _auth_states:
        current_app.logger.warning(
            f"Invalid or missing state: {state[:8] if state else 'None'}..."
        )
        return None

    state_data = _auth_states.get(state)

    ttl = current_app.config.get("AUTH_STATE_TTL", 300)
    if time.time() - state_data["created_at"] > ttl:
        current_app.logger.warning(f"Expired state: {state[:8]}...")
        del _auth_states[state]
        return None

    device_id = state_data["device_id"]
    del _auth_states[state]

    current_app.logger.info(f"Validated state for device {device_id}")
    return device_id


def generate_spotify_auth_url(device_id: str) -> str:
    """
    Generate Spotify authorization URL for OAuth2 flow.

    Args:
        device_id: Unique identifier for the device.

    Returns:
        str: The complete authorization URL for Spotify OAuth2.

    Raises:
        ValueError: If required configuration is missing.
    """
    client_id = current_app.config.get("SPOTIFY_CLIENT_ID")

    if not client_id:
        raise ValueError("SPOTIFY_CLIENT_ID not configured")

    state = _generate_state(device_id)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "scope": current_app.config.get("SPOTIFY_SCOPE"),
        "redirect_uri": current_app.config.get("SPOTIFY_REDIRECT_URI"),
    }

    auth_url = f"{current_app.config.get('SPOTIFY_AUTH_URL')}?{urlencode(params)}"

    current_app.logger.info(f"Generated auth URL for device {device_id}")
    return auth_url


def process_callback(state: str, code: str) -> Tuple[bool, str]:
    """
    Process OAuth2 callback from Spotify.

    Args:
        state: State parameter from the callback.
        code: Authorization code from Spotify.

    Returns:
        Tuple[bool, str]: (success, message/error)

    Raises:
        ValueError: If state is invalid or code exchange fails.
    """
    device_id = _validate_state(state)
    if not device_id:
        raise ValueError("Invalid or expired state parameter")

    try:
        tokens = _exchange_code_for_tokens(code)
    except Exception as e:
        current_app.logger.error(f"Token exchange failed: {str(e)}")
        raise ValueError(f"Failed to exchange code: {str(e)}")

    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        device = DeviceAuth(device_id=device_id)
        db.session.add(device)
        current_app.logger.info(f"Creating new device record: {device_id}")
    else:
        current_app.logger.info(f"Updating existing device: {device_id}")

    device.set_tokens(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        scope=tokens["scope"],
    )

    try:
        db.session.commit()
        current_app.logger.info(f"Successfully authenticated device {device_id}")
        return True, f"Device {device_id} successfully authenticated"
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database error: {str(e)}")
        raise ValueError(f"Failed to save authentication: {str(e)}")


def _exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Spotify.

    Returns:
        dict: Token response from Spotify.

    Raises:
        requests.RequestException: If the API request fails.
    """
    client_id = current_app.config.get("SPOTIFY_CLIENT_ID")
    client_secret = current_app.config.get("SPOTIFY_CLIENT_SECRET")

    if not all([client_id, client_secret]):
        raise ValueError("Missing Spotify API configuration")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": current_app.config.get("SPOTIFY_REDIRECT_URI"),
        "client_id": client_id,
        "client_secret": client_secret,
    }

    response = requests.post(
        current_app.config.get("SPOTIFY_TOKEN_URL"), data=token_data, timeout=10
    )

    if response.status_code != 200:
        error_data = response.json() if response.text else {}
        error_msg = error_data.get("error_description", "Unknown error")
        raise requests.RequestException(f"Token exchange failed: {error_msg}")

    return response.json()


def refresh_token_for_device(device_id: str) -> bool:
    """
    Refresh access token for a device using its refresh token.

    Args:
        device_id: The device identifier.

    Returns:
        bool: True if refresh successful, False otherwise.
    """
    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        current_app.logger.error(f"Device not found: {device_id}")
        return False

    try:
        refresh_token = device.refresh_token
    except Exception as e:
        current_app.logger.error(f"Failed to decrypt refresh token: {str(e)}")
        return False

    client_id = current_app.config.get("SPOTIFY_CLIENT_ID")
    client_secret = current_app.config.get("SPOTIFY_CLIENT_SECRET")

    refresh_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": current_app.config.get("SPOTIFY_REDIRECT_URI"),
    }

    try:
        response = requests.post(
            current_app.config.get("SPOTIFY_TOKEN_URL"), data=refresh_data, timeout=10
        )

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error_description", "Unknown error")
            current_app.logger.error(
                f"Token refresh failed for {device_id}: {error_msg}"
            )
            return False

        token_data = response.json()

        # Update tokens
        device.set_tokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_in=token_data["expires_in"],
            scope=token_data["scope"],
        )

        db.session.commit()
        current_app.logger.info(f"Successfully refreshed token for device {device_id}")
        return True

    except requests.RequestException as e:
        current_app.logger.error(f"Network error during token refresh: {str(e)}")
        return False
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error during token refresh: {str(e)}")
        return False


def get_valid_token(device_id: str) -> Optional[str]:
    """
    Get a valid access token for a device, refreshing if necessary.

    Args:
        device_id: The device identifier.

    Returns:
        Optional[str]: Valid access token or None if unable to get one.
    """
    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        current_app.logger.warning(f"Device not found: {device_id}")
        return None

    if device.is_token_expired:
        current_app.logger.info(
            f"Token expired for device {device_id}, attempting refresh"
        )

        if not refresh_token_for_device(device_id):
            current_app.logger.error(f"Failed to refresh token for device {device_id}")
            return None

        db.session.refresh(device)

    try:
        return device.access_token
    except Exception as e:
        current_app.logger.error(f"Failed to decrypt access token: {str(e)}")
        return None


# Utility function for debugging
def get_device_status(device_id: str) -> dict:
    """
    Get authentication status for a device.

    Args:
        device_id: The device identifier.

    Returns:
        dict: Status information about the device.
    """
    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        return {"exists": False, "device_id": device_id}

    return {
        "exists": True,
        "device_id": device_id,
        "is_expired": device.is_token_expired,
        "expires_at": device.expires_at.isoformat() if device.expires_at else None,
        "time_until_expiry": (
            str(device.time_until_expiry) if device.time_until_expiry else None
        ),
        "has_required_scopes": device.has_required_scopes,
        "last_updated": device.updated_at.isoformat() if device.updated_at else None,
    }
