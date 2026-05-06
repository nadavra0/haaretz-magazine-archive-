#!/usr/bin/env python3
"""
Haaretz Magazine Archive — Web App
Usage: python app.py
Then open: http://localhost:5001
"""

from flask import Flask, jsonify, send_from_directory, abort
import json
import os
import subprocess
import sys

ARCHIVE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ARCHIVE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    # Serve API routes separately; everything else → React's index.html
    if path.startswith("api/"):
        abort(404)
    full = os.path.join(STATIC_DIR, path)
    if path and os.path.isfile(full):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/issues")
def api_issues():
    data = load_json(os.path.join(ARCHIVE_DIR, "index.json"))
    if not data:
        return jsonify({"issues": [], "last_updated": None, "total_issues": 0})
    return jsonify(data)


@app.route("/api/issues/<magazine_date>")
def api_issue(magazine_date):
    issue = load_json(os.path.join(ARCHIVE_DIR, "issues", f"{magazine_date}.json"))
    if not issue:
        abort(404)
    return jsonify(issue)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger a re-scrape in the background."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(ARCHIVE_DIR, "scraper.py"), "--fetch-titles"],
            cwd=ARCHIVE_DIR
        )
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    index_path = os.path.join(ARCHIVE_DIR, "index.json")
    if not os.path.exists(index_path):
        print("No archive found. Run first scrape? (y/n): ", end="")
        if input().strip().lower() == "y":
            os.system(f"{sys.executable} {ARCHIVE_DIR}/scraper.py")

    print()
    print("=" * 40)
    print("  Haaretz Magazine Archive")
    print("  http://localhost:5001")
    print("=" * 40)
    print()
    app.run(host="0.0.0.0", port=5001, debug=False)
