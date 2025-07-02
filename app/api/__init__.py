"""
API package for Spotify Voice Bridge.

This package contains the API routes and database models.
"""

from flask import Blueprint

api_bp = Blueprint("api", __name__)

from app.api import routes

__all__ = ["api_bp"]
