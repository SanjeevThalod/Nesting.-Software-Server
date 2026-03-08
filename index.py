"""
Vercel serverless entry point.
Exposes the FastAPI app for Vercel's Python runtime.
"""
from main import app

__all__ = ["app"]
