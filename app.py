
import os
import json
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

MIN_PRICE = 0.25
MAX_PRICE = 5.00

DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/data"))

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_file = DATA_DIR / ".write_test"
    test_file.write_text("test")
    test_file.unlink()
except OSError:
    DATA_DIR = Path(app.root_path) / "instance"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "buyer_shared.db"

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

        db.execute(
            """
            INSERT OR IGNORE INTO shared_settings (id, settings)
            VALUES (1, ?)
            """,
            (json.dumps(DEFAULT_SETTINGS),),
        )

        row = db.execute(
            "SELECT settings FROM shared_settings WHERE id = 1"
        ).fetchone()

        if row:
            try:
                saved = json.loads(row["settings"])
                changed = False

                for offer in saved.get("offers", []):
                    price = offer.get("price")
                    if (
                        isinstance(price, (int, float))
                        and not isinstance(price, bool)
                        and not MIN_PRICE <= price <= MAX_PRICE
                    ):
                        offer["price"] = 2.50
                        changed = True

                if changed:
                    db.execute(
                        "UPDATE shared_settings SET settings = ? WHERE id = 1",
                        (json.dumps(saved),),
                    )
            except (ValueError, TypeError, AttributeError):
                db.execute(
                    "UPDATE shared_settings SET settings = ? WHERE id = 1",
                    (json.dumps(DEFAULT_SETTINGS),),
                )


def read_settings():
    with connect_db() as db:
        row = db.execute(
            "SELECT settings FROM shared_settings WHERE id = 1"
        ).fetchone()

    if not row:
        return DEFAULT_SETTINGS

    try:
        return json.loads(row["settings"])
    except (ValueError, TypeError):
        return DEFAULT_SETTINGS


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid settings.")

    price_weight = data.get("priceWeight")
    quality_weight = data.get("qualityWeight")
    target_quantity = data.get("targetQuantity")
    offers = data.get("offers")

    # Weights only need to be valid numeric values.
    # They do not need to total 100 or stay between 0 and 100.
    for weight in (price_weight, quality_weight):
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("Enter valid numeric weights.")

    if (
        isinstance(target_quantity, bool)
        or not isinstance(target_quantity, int)
        or target_quantity < 0
    ):
        raise ValueError("Target quantity must be a whole number of zero or more.")

    expected_groups = {"1", "2", "3", "5"}

    if not isinstance(offers, list) or len(offers) != 4:
        raise ValueError("Exactly four seller offers are required.")

    cleaned_offers = []

    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError("Invalid seller offer.")

        group = str(offer.get("group"))

        if group not in expected_groups:
            raise ValueError("Unexpected seller group.")

        price = offer.get("price")
        quality = offer.get("quality")
        stock = offer.get("stock")

        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not MIN_PRICE <= price <= MAX_PRICE
        ):
            raise ValueError(
                "Maximum price is $5.00 per soldier. "
                "Prices must be between $0.25 and $5.00."
            )

        if (
            isinstance(quality, bool)
            or not isinstance(quality, (int, float))
            or not 1 <= quality <= 10
        ):
            raise ValueError("Quality ratings must be between 1 and 10.")

        if (
            isinstance(stock, bool)
            or not isinstance(stock, int)
            or stock < 0
        ):
            raise ValueError("Stock must be a whole number of zero or more.")

        cleaned_offers.append({
            "group": group,
            "price": round(float(price), 2),
            "quality": quality,
            "stock": stock,
        })

    if {offer["group"] for offer in cleaned_offers} != expected_groups:
        raise ValueError("Each seller group must appear exactly once.")

    return {
        "priceWeight": price_weight,
        "qualityWeight": quality_weight,
        "targetQuantity": target_quantity,
        "offers": cleaned_offers,
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

    return jsonify({
        "message": "Shared settings saved successfully.",
        "settings": settings,
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "minimumPrice": MIN_PRICE,
        "maximumPrice": MAX_PRICE,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
