import os
import json
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Persistent storage on Render.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/data"))

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_file = DATA_DIR / ".write_test"
    test_file.touch(exist_ok=True)
    test_file.unlink(missing_ok=True)
except OSError:
    DATA_DIR = Path(app.root_path) / "instance"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "buyer_shared.db"

MIN_PRICE = 0.25
MAX_PRICE = 5.00

DEFAULT_SETTINGS = {
    "priceWeight": 50,
    "qualityWeight": 50,
    "targetQuantity": 10,
    "offers": [
        {"group": "1", "price": 2.50, "quality": 8, "stock": 10},
        {"group": "2", "price": 2.50, "quality": 7, "stock": 10},
        {"group": "3", "price": 2.50, "quality": 6, "stock": 10},
        {"group": "5", "price": 2.50, "quality": 5, "stock": 10},
    ],
}

EXPECTED_GROUPS = {"1", "2", "3", "5"}


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS shared_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                settings TEXT NOT NULL
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO shared_settings (id, settings)
            VALUES (1, ?)
        """, (json.dumps(DEFAULT_SETTINGS),))


def read_settings():
    with connect_db() as db:
        row = db.execute(
            "SELECT settings FROM shared_settings WHERE id = 1"
        ).fetchone()

    if row is None:
        return DEFAULT_SETTINGS.copy()

    try:
        return json.loads(row["settings"])
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_SETTINGS.copy()


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object.")

    pw = data.get("priceWeight")
    qw = data.get("qualityWeight")
    target = data.get("targetQuantity")
    offers = data.get("offers")

    # Validate the price and quality weights.
    if (
        isinstance(pw, bool)
        or not isinstance(pw, (int, float))
        or isinstance(qw, bool)
        or not isinstance(qw, (int, float))
        or not 0 <= pw <= 100
        or not 0 <= qw <= 100
        or abs(pw + qw - 100) > 0.000001
    ):
        raise ValueError(
            "Price and quality weights must add up to 100%."
        )

    # Validate target quantity.
    if (
        isinstance(target, bool)
        or not isinstance(target, int)
        or target < 0
    ):
        raise ValueError(
            "Target quantity must be a whole number of zero or more."
        )

    # Require one offer for each seller group.
    if not isinstance(offers, list) or len(offers) != 4:
        raise ValueError("Exactly four seller offers are required.")

    cleaned = []
    seen_groups = set()

    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError("Each offer must be an object.")

        group = str(offer.get("group"))

        if group not in EXPECTED_GROUPS:
            raise ValueError("Unexpected seller group.")

        if group in seen_groups:
            raise ValueError("Each seller group must appear only once.")

        seen_groups.add(group)

        price = offer.get("price")
        quality = offer.get("quality")
        stock = offer.get("stock")

        # Seller price must be between $0.25 and $5.00.
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not MIN_PRICE <= price <= MAX_PRICE
        ):
            raise ValueError(
                "Offer prices must be between $0.25 and $5.00."
            )

        # Quality must be from 1 to 10.
        if (
            isinstance(quality, bool)
            or not isinstance(quality, (int, float))
            or not 1 <= quality <= 10
        ):
            raise ValueError(
                "Quality ratings must be from 1 to 10."
            )

        # Stock must be a nonnegative whole number.
        if (
            isinstance(stock, bool)
            or not isinstance(stock, int)
            or stock < 0
        ):
            raise ValueError(
                "Stock must be a whole number of zero or more."
            )

        cleaned.append({
            "group": group,
            "price": round(float(price), 2),
            "quality": quality,
            "stock": stock,
        })

    if seen_groups != EXPECTED_GROUPS:
        raise ValueError(
            "Groups 1, 2, 3, and 5 must each have one offer."
        )

    return {
        "priceWeight": pw,
        "qualityWeight": qw,
        "targetQuantity": target,
        "offers": cleaned,
    }


initialize_db()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/shared-settings", methods=["GET"])
def get_shared_settings():
    response = jsonify(read_settings())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/shared-settings", methods=["PUT"])
def save_shared_settings():
    data = request.get_json(silent=True)

    try:
        settings = validate_settings(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    with connect_db() as db:
        db.execute(
            """
            INSERT INTO shared_settings (id, settings)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET settings = excluded.settings
            """,
            (json.dumps(settings),),
        )

    response = jsonify({
        "message": "Shared settings saved successfully.",
        "settings": settings,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "min_price": MIN_PRICE,
        "max_price": MAX_PRICE,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
