"""Local dev entrypoint. Run with: python app.py

(Vercel itself uses api/index.py as the serverless entrypoint — this file
just makes local testing match the familiar `python app.py` workflow.)
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
