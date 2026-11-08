#!/usr/bin/env python3
"""
Wortklar Server Entrypoint.
Runs the Flask application on the loopback interface (127.0.0.1) with debug off.

Usage:
    # macOS / Linux:
    python3 run.py

    # Windows:
    python run.py
"""

import os
import sys
from wortklar.app import create_app

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    db_path = os.environ.get("WORTKLAR_DB", os.path.join(os.path.dirname(__file__), "wortklar.db"))

    app = create_app(db_path=db_path)
    print("=" * 60)
    print(f" Starting Wortklar on http://{host}:{port}")
    print(f" Database: {db_path}")
    print(" Loopback interface active. Debug mode disabled.")
    print("=" * 60)
    try:
        app.run(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)

