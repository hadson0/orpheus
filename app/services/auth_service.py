from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urlencode

import requests
from flask import current_app

from app import db
from app.api.models import DeviceAuth

_DEFAULT_TTL = 300  # seconds


def _cfg(key: str, default: Any = None) -> Any:
    return current_app.config.get(key, default)


def _now_ts() -> float:
    return time.time()


def _log_exc(msg: str, exc: Exception) -> None:
    current_app.logger.error("%s – %s", msg, exc)


@dataclass
class _StateEntry:
    device_id: str
    created_at: float


_AUTH_STATES: Dict[str, _StateEntry] = {}


def _cleanup_states() -> None:
    """Remove expired entries from _AUTH_STATES."""
    ttl = _cfg("AUTH_STATE_TTL", _DEFAULT_TTL)
    now = _now_ts()
    expired = [s for s, d in _AUTH_STATES.items() if now - d.created_at > ttl]
    for s in expired:
        _AUTH_STATES.pop(s, None)
        current_app.logger.debug("Cleaned expired state: %s…", s[:8])


def _generate_state(device_id: str) -> str:
    _cleanup_states()
    state = secrets.token_urlsafe(4)
    _AUTH_STATES[state] = _StateEntry(device_id, _now_ts())
    current_app.logger.info("Generated auth state for %s", device_id)
    return state


def _validate_state(state: str) -> Optional[str]:
    """Return device_id if valid, else None."""
    entry = _AUTH_STATES.pop(state, None)
    if not entry:
        current_app.logger.warning(
            "Unknown state param: %s", state[:8] if state else ""
        )
        return None

    ttl = _cfg("AUTH_STATE_TTL", _DEFAULT_TTL)
    if _now_ts() - entry.created_at > ttl:
        current_app.logger.warning("Expired state: %s…", state[:8])
        return None
    current_app.logger.info("Validated state for device %s", entry.device_id)
    return entry.device_id


def generate_spotify_auth_url(device_id: str) -> str:
    client_id = _cfg("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise ValueError("SPOTIFY_CLIENT_ID not configured")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": _generate_state(device_id),
        "scope": _cfg("SPOTIFY_SCOPE"),
        "redirect_uri": _cfg("SPOTIFY_REDIRECT_URI"),
    }
    url = f"{_cfg('SPOTIFY_AUTH_URL')}?{urlencode(params)}"
    current_app.logger.info("Generated auth URL for %s", device_id)
    return url


def process_callback(state: str, code: str) -> Tuple[bool, str]:
    device_id = _validate_state(state)
    if not device_id:
        raise ValueError("Invalid or expired state parameter")

    tokens = _exchange_code_for_tokens(code)
    
    current_app.logger.info("Processing callback for %s", device_id)
    current_app.logger.info("Tokens: %s", tokens)
    

    device = DeviceAuth.get_by_device_id(device_id) or DeviceAuth(device_id=device_id)
    if device not in db.session:
        db.session.add(device)

    device.set_tokens(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        scope=tokens["scope"],
    )

    try:
        db.session.commit()
        current_app.logger.info("Authenticated device %s", device_id)
        return True, f"Device {device_id} successfully authenticated"
    except Exception as exc:
        db.session.rollback()
        _log_exc("DB error saving authentication", exc)
        raise ValueError("Failed to save authentication") from exc


def refresh_token_for_device(device_id: str) -> bool:
    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        current_app.logger.error("Device not found: %s", device_id)
        return False

    try:
        refresh_token = device.refresh_token
    except Exception as exc:
        _log_exc("Refresh token decrypt failed", exc)
        return False

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _cfg("SPOTIFY_CLIENT_ID"),
        "client_secret": _cfg("SPOTIFY_CLIENT_SECRET"),
        "redirect_uri": _cfg("SPOTIFY_REDIRECT_URI"),
    }

    try:
        rsp = requests.post(_cfg("SPOTIFY_TOKEN_URL"), data=payload, timeout=10)
        if rsp.status_code != 200:
            err = (
                rsp.json().get("error_description", "Unknown error")
                if rsp.text
                else "unknown"
            )
            current_app.logger.error("Token refresh failed for %s: %s", device_id, err)
            return False

        data = rsp.json()
        device.set_tokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in=data["expires_in"],
            scope=data["scope"],
        )
        db.session.commit()
        current_app.logger.info("Refreshed token for %s", device_id)
        return True
    except requests.RequestException as exc:
        _log_exc("Network error during token refresh", exc)
        return False
    except Exception as exc:
        db.session.rollback()
        _log_exc("Unexpected error during token refresh", exc)
        return False


def get_valid_token(device_id: str) -> Optional[str]:
    device = DeviceAuth.get_by_device_id(device_id)
    if not device:
        current_app.logger.warning("Device not found: %s", device_id)
        return None

    if device.is_token_expired:
        current_app.logger.info("Token expired for %s – refreshing", device_id)
        if not refresh_token_for_device(device_id):
            return None
        db.session.refresh(device)

    try:
        return device.access_token
    except Exception as exc:
        _log_exc("Access token decrypt failed", exc)
        return None


def _exchange_code_for_tokens(code: str) -> dict:
    client_id = _cfg("SPOTIFY_CLIENT_ID")
    client_secret = _cfg("SPOTIFY_CLIENT_SECRET")
    if not all((client_id, client_secret)):
        raise ValueError("Missing Spotify API configuration")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _cfg("SPOTIFY_REDIRECT_URI"),
        "client_id": client_id,
        "client_secret": client_secret,
    }

    rsp = requests.post(_cfg("SPOTIFY_TOKEN_URL"), data=data, timeout=10)
    if rsp.status_code != 200:
        err = (
            rsp.json().get("error_description", "Unknown error")
            if rsp.text
            else "unknown"
        )
        raise requests.RequestException(f"Token exchange failed: {err}")

    return rsp.json()


def get_device_status(device_id: str) -> dict:
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
