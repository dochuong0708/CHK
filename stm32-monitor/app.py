"""Flask dashboard backend for an STM32 Blue Pill serial monitor."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import serial
from flask import Flask, jsonify, render_template, request
from serial import SerialException

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "monitor.db"
BAUD_RATE = 115200
STALE_AFTER_SECONDS = 3

app = Flask(__name__)
state_lock = threading.RLock()
serial_lock = threading.Lock()
latest_state: dict[str, Any] = {}
connection_status: dict[str, Any] = {
    "connected": False,
    "port": os.getenv("STM32_PORT", "COM3"),
    "last_seen": None,
    "error": None,
}
serial_port: serial.Serial | None = None


def timestamp() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a database connection and always close it after use."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the sensor and event history tables if needed."""
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sensor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                temperature REAL,
                smoke_raw INTEGER,
                smoke_percent REAL,
                led1 INTEGER,
                led2 INTEGER,
                led3 INTEGER,
                fan INTEGER,
                button1 INTEGER,
                button2 INTEGER
            );
            CREATE TABLE IF NOT EXISTS event_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL
            );
            """
        )


def save_event(event_type: str, details: str) -> None:
    """Store a concise event record."""
    with get_db() as connection:
        connection.execute(
            "INSERT INTO event_history (timestamp, event_type, details) VALUES (?, ?, ?)",
            (timestamp(), event_type, details[:500]),
        )


def valid_state(message: Any) -> bool:
    """Check that a UART message has the expected state shape and safe values."""
    if not isinstance(message, dict) or message.get("type") != "state":
        return False
    numeric_fields = ("temperature", "smoke_raw", "smoke_percent", "fan")
    binary_fields = ("led1", "led2", "led3", "button1", "button2")
    try:
        for field in numeric_fields:
            if field in message and not isinstance(message[field], (int, float)):
                return False
        for field in binary_fields:
            if field in message and message[field] not in (0, 1, False, True):
                return False
    except (TypeError, ValueError):
        return False
    return True


def record_state(message: dict[str, Any]) -> None:
    """Publish a valid device sample and persist it to SQLite."""
    row = {
        "temperature": message.get("temperature"),
        "smoke_raw": message.get("smoke_raw"),
        "smoke_percent": message.get("smoke_percent"),
        "led1": message.get("led1"),
        "led2": message.get("led2"),
        "led3": message.get("led3"),
        "fan": message.get("fan"),
        "button1": message.get("button1"),
        "button2": message.get("button2"),
    }
    seen = timestamp()
    with state_lock:
        latest_state.clear()
        latest_state.update(row)
        connection_status.update(connected=True, last_seen=seen, error=None)
    with get_db() as connection:
        connection.execute(
            """INSERT INTO sensor_history
               (timestamp, temperature, smoke_raw, smoke_percent, led1, led2, led3,
                fan, button1, button2)
               VALUES (:timestamp, :temperature, :smoke_raw, :smoke_percent, :led1,
                       :led2, :led3, :fan, :button1, :button2)""",
            {"timestamp": seen, **row},
        )


def serial_reader() -> None:
    """Read JSON lines from the configured UART port in a background thread."""
    global serial_port
    port_name = os.getenv("STM32_PORT", "COM3").strip()
    if not port_name:
        with state_lock:
            connection_status.update(port=None, error="STM32_PORT is not configured")
        return
    with state_lock:
        connection_status["port"] = port_name

    while True:
        try:
            with serial.Serial(port_name, BAUD_RATE, timeout=1, write_timeout=1) as port:
                with serial_lock:
                    serial_port = port
                with state_lock:
                    connection_status.update(connected=False, error=None)
                save_event("serial", f"Opened {port_name} at {BAUD_RATE} baud")
                while True:
                    raw_line = port.readline()
                    if not raw_line:
                        continue
                    try:
                        message = json.loads(raw_line.decode("utf-8").strip())
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        save_event("serial_error", "Ignored malformed UART JSON line")
                        continue
                    if valid_state(message):
                        record_state(message)
        except (SerialException, OSError) as error:
            with state_lock:
                connection_status.update(connected=False, error=str(error))
            serial_port = None
            time.sleep(2)


def start_serial_reader() -> None:
    """Start the UART reader once for the Flask process."""
    if os.getenv("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        threading.Thread(target=serial_reader, name="stm32-serial-reader", daemon=True).start()


@app.get("/")
def index():
    """Render the monitoring dashboard."""
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    """Return the latest sensor sample and a freshness-aware connection status."""
    with state_lock:
        state = dict(latest_state)
        status = dict(connection_status)
    last_seen = status.get("last_seen")
    if last_seen:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds()
            if age > STALE_AFTER_SECONDS:
                status["connected"] = False
        except ValueError:
            status["connected"] = False
    return jsonify({"state": state, "connection": status})


@app.get("/api/history")
def api_history():
    """Return up to 1000 sensor samples in chronological order."""
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
    except ValueError:
        limit = 100
    with get_db() as connection:
        rows = connection.execute(
            """SELECT timestamp, temperature, smoke_raw, smoke_percent, led1, led2, led3,
                      fan, button1, button2 FROM sensor_history ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return jsonify([dict(row) for row in reversed(rows)])


@app.get("/api/events")
def api_events():
    """Return the latest 100 recorded system events."""
    with get_db() as connection:
        rows = connection.execute(
            "SELECT timestamp, event_type, details FROM event_history ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/control")
def api_control():
    """Validate and forward LED or fan control values to the STM32."""
    data = request.get_json(silent=True)
    allowed = {"led1", "led2", "led3", "fan"}
    if not isinstance(data, dict) or not data or not set(data).issubset(allowed):
        return jsonify({"error": "JSON command must contain LED or fan fields"}), 400
    command: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, int):
            return jsonify({"error": f"{key} must be an integer"}), 400
        if key == "fan" and not 0 <= value <= 100:
            return jsonify({"error": "fan must be between 0 and 100"}), 400
        if key.startswith("led") and value not in (0, 1):
            return jsonify({"error": f"{key} must be 0 or 1"}), 400
        command[key] = value

    with serial_lock:
        port = serial_port
        if port is None or not port.is_open:
            return jsonify({"error": "STM32 serial port is disconnected"}), 503
        try:
            payload = {"cmd": "set", **command}
            port.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        except (SerialException, OSError) as error:
            save_event("control_error", str(error))
            return jsonify({"error": "Could not send command to STM32"}), 503
    save_event("control", json.dumps(command, ensure_ascii=False))
    return jsonify({"ok": True, "sent": command})


if __name__ == "__main__":
    init_db()
    start_serial_reader()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
