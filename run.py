"""Local entry point:  python run.py   (then open http://localhost:8000 on your phone's browser)"""
import os

from finn.app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), threaded=True)
