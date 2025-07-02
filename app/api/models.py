"""
Database models for Spotify Voice Bridge API.

This module defines the SQLAlchemy models for storing device authentication data with encrypted tokens.
"""

from typing import Optional
from datetime import datetime, timedelta, timezone
from app import db
from app.utils.encryption import encrypt, decrypt
from sqlalchemy import event
from flask import current_app


class DeviceAuth(db.Model):
    """
    Model for storing device authentication data.

    Each device has its own Spotify authentication tokens stored in an encrypted format for security.
    """

    __tablename__ = "device_auth"

    # Primary key - unique device identifier
    device_id = db.Column(db.String(255), primary_key=True)

    encrypted_access_token = db.Column(db.LargeBinary, nullable=False)
    encrypted_refresh_token = db.Column(db.LargeBinary, nullable=False)

    expires_at = db.Column(db.DateTime, nullable=False)
    scope = db.Column(db.String(512), nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # User information (for debugging/logging)
    spotify_user_id = db.Column(db.String(255), nullable=True)

    def __repr__(self) -> str:
        """String representation of DeviceAuth instance."""
        return f"<DeviceAuth {self.device_id}>"

    def set_tokens(
        self, access_token: str, refresh_token: str, expires_in: int, scope: str
    ) -> None:
        """
        Set and encrypt authentication tokens.

        Args:
            access_token: Spotify access token.
            refresh_token: Spotify refresh token.
            expires_in: Token lifetime in seconds.
            scope: Space-separated list of granted scopes.
        """
        if not all([access_token, refresh_token, expires_in, scope]):
            raise ValueError("All token parameters are required")

        try:
            self.encrypted_access_token = encrypt(access_token)
            self.encrypted_refresh_token = encrypt(refresh_token)

            self.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in
            )
            self.updated_at = datetime.now(timezone.utc)

            self.scope = scope

            current_app.logger.info(
                f"Tokens set for device {self.device_id}, expires at {self.expires_at}"
            )

        except Exception as e:
            current_app.logger.error(
                f"Failed to set tokens for device {self.device_id}: {str(e)}"
            )
            raise

    @property
    def access_token(self) -> str:
        """
        Get decrypted access token.

        Returns:
            str: The decrypted access token.

        Raises:
            ValueError: If decryption fails.
        """
        try:
            return decrypt(self.encrypted_access_token)
        except Exception as e:
            current_app.logger.error(
                f"Failed to decrypt access token for device {self.device_id}: {str(e)}"
            )
            raise ValueError("Failed to decrypt access token")

    @property
    def refresh_token(self) -> str:
        """
        Get decrypted refresh token.

        Returns:
            str: The decrypted refresh token.

        Raises:
            ValueError: If decryption fails.
        """
        try:
            return decrypt(self.encrypted_refresh_token)
        except Exception as e:
            current_app.logger.error(
                f"Failed to decrypt refresh token for device {self.device_id}: {str(e)}"
            )
            raise ValueError("Failed to decrypt refresh token")

    @property
    def is_token_expired(self) -> bool:
        """
        Check if the access token is expired.

        Returns True if the token is expired or will expire within the next 60 seconds.
        This buffer helps prevent edge cases where the token expires during use.

        Returns:
            bool: True if token is expired or about to expire, False otherwise.
        """
        if not self.expires_at:
            return True

        # Add 60-second buffer to prevent edge cases
        expiry_with_buffer = self.expires_at - timedelta(seconds=60)
        is_expired = datetime.utcnow() >= expiry_with_buffer

        if is_expired:
            current_app.logger.debug(
                f"Token for device {self.device_id} is expired or about to expire"
            )

        return is_expired

    @property
    def time_until_expiry(self) -> Optional[timedelta]:
        """
        Get time remaining until token expiry.

        Returns:
            Optional[timedelta]: Time until expiry, or None if already expired.
        """
        if not self.expires_at:
            return None

        remaining = self.expires_at - datetime.utcnow()
        return remaining if remaining.total_seconds() > 0 else None

    @property
    def has_required_scopes(self) -> bool:
        """
        Check if the device has all required Spotify scopes.

        Returns:
            bool: True if all required scopes are present.
        """
        required_scopes = {"user-read-playback-state", "user-modify-playback-state"}
        granted_scopes = set(self.scope.split()) if self.scope else set()
        return required_scopes.issubset(granted_scopes)

    def update_spotify_user_id(self, user_id: str) -> None:
        """
        Update the Spotify user ID associated with this device.

        Args:
            user_id: Spotify user ID.
        """
        self.spotify_user_id = user_id
        self.updated_at = datetime.utcnow()

    @classmethod
    def get_by_device_id(cls, device_id: str) -> Optional["DeviceAuth"]:
        """
        Get a device by its ID.

        Args:
            device_id: The device identifier.

        Returns:
            Optional[DeviceAuth]: The device instance or None if not found.
        """
        return cls.query.filter_by(device_id=device_id).first()

    @classmethod
    def delete_expired_devices(cls, days: int = 30) -> int:
        """
        Delete devices that haven't been updated in the specified number of days.

        Args:
            days: Number of days of inactivity before deletion.

        Returns:
            int: Number of devices deleted.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        expired_devices = cls.query.filter(cls.updated_at < cutoff_date).all()

        count = len(expired_devices)
        for device in expired_devices:
            db.session.delete(device)

        if count > 0:
            db.session.commit()
            current_app.logger.info(f"Deleted {count} expired devices")

        return count


@event.listens_for(DeviceAuth, "before_insert")
def device_before_insert(mapper, connection, target):
    """Log device creation."""
    current_app.logger.info(f"Creating new device: {target.device_id}")


@event.listens_for(DeviceAuth, "before_delete")
def device_before_delete(mapper, connection, target):
    """Log device deletion."""
    current_app.logger.info(f"Deleting device: {target.device_id}")


class ShortURL(db.Model):
    __tablename__ = "short_urls"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)
    long_url = db.Column(db.String(2048), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
