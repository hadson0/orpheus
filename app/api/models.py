from __future__ import annotations

import datetime as dt
from typing import Optional, Set, List

from flask import current_app
from sqlalchemy import event
from app import db
from app.utils.encryption import encrypt, decrypt

UTC = dt.timezone.utc
REQUIRED_SCOPES: Set[str] = {"user-read-playback-state", "user-modify-playback-state"}


def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


def _log_exc(msg: str, exc: Exception) -> None:
    current_app.logger.error("%s – %s", msg, exc)


class TimestampMixin:
    """Adds created_at and updated_at columns."""

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DeviceAuth(TimestampMixin, db.Model):
    """Stores encrypted Spotify OAuth credentials per device."""

    __tablename__ = "device_auth"

    device_id = db.Column(db.String(255), primary_key=True)
    encrypted_access_token = db.Column(db.LargeBinary, nullable=False)
    encrypted_refresh_token = db.Column(db.LargeBinary, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    scope = db.Column(db.String(512), nullable=False)
    spotify_user_id = db.Column(db.String(255))

    def __repr__(self) -> str:
        return f"<DeviceAuth {self.device_id}>"

    def set_tokens(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str,
    ) -> None:
        """Encrypt and save new tokens."""
        if not all((access_token, refresh_token, expires_in, scope)):
            raise ValueError("All token parameters are required")
        try:
            self.encrypted_access_token = encrypt(access_token)
            self.encrypted_refresh_token = encrypt(refresh_token)
            self.expires_at = _utcnow() + dt.timedelta(seconds=expires_in)
            self.scope = scope
            current_app.logger.info(
                "Tokens set for device %s – expires at %s",
                self.device_id,
                self.expires_at.isoformat(),
            )
        except Exception as exc:
            _log_exc(f"Failed to set tokens for {self.device_id}", exc)
            raise

    @property
    def access_token(self) -> str:
        try:
            return decrypt(self.encrypted_access_token)
        except Exception as exc:
            _log_exc(f"Access token decrypt failed for {self.device_id}", exc)
            raise ValueError("Failed to decrypt access token") from exc

    @property
    def refresh_token(self) -> str:
        try:
            return decrypt(self.encrypted_refresh_token)
        except Exception as exc:
            _log_exc(f"Refresh token decrypt failed for {self.device_id}", exc)
            raise ValueError("Failed to decrypt refresh token") from exc

    @property
    def is_token_expired(self) -> bool:
        """True if token expires within 60 seconds."""
        if not self.expires_at:
            return True
        return _utcnow() >= self.expires_at - dt.timedelta(seconds=60)

    @property
    def time_until_expiry(self) -> Optional[dt.timedelta]:
        if not self.expires_at:
            return None
        remaining = self.expires_at - _utcnow()
        return remaining if remaining.total_seconds() > 0 else None

    @property
    def has_required_scopes(self) -> bool:
        granted = set(self.scope.split()) if self.scope else set()
        return REQUIRED_SCOPES.issubset(granted)

    def update_spotify_user_id(self, user_id: str) -> None:
        self.spotify_user_id = user_id
        self.updated_at = _utcnow()

    @classmethod
    def get_by_device_id(cls, device_id: str) -> Optional["DeviceAuth"]:
        return cls.query.filter_by(device_id=device_id).first()

    @classmethod
    def delete_expired_devices(cls, days: int = 30) -> int:
        """Delete devices not updated for `days` days. Returns count."""
        cutoff = _utcnow() - dt.timedelta(days=days)
        expired: List["DeviceAuth"] = cls.query.filter(cls.updated_at < cutoff).all()
        for device in expired:
            db.session.delete(device)
        if expired:
            db.session.commit()
            current_app.logger.info("Deleted %s expired devices", len(expired))
        return len(expired)


@event.listens_for(DeviceAuth, "before_insert")
def _before_insert(_, __, target):
    current_app.logger.info("Creating new device: %s", target.device_id)


@event.listens_for(DeviceAuth, "before_delete")
def _before_delete(_, __, target):
    current_app.logger.info("Deleting device: %s", target.device_id)


class ShortURL(TimestampMixin, db.Model):
    __tablename__ = "short_urls"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)
    long_url = db.Column(db.String(2048), nullable=False)
