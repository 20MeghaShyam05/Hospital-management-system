"""Root ASGI entrypoint for the fractal DPAMS application."""

from features.core.app import app, create_app

__all__ = ["app", "create_app"]
