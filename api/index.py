"""Vercel serverless entry point."""
from app.main import app

# Vercel looks for `app` in this module
handler = app
