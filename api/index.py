# Vercel serverless function entry point
# This file makes the Flask app work with Vercel

import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app

# Vercel requires the app to be named 'app'
# Export for Vercel
handler = app
