# STM32 Blue Pill Monitor

Standalone Flask dashboard for an STM32F103C8T6 Blue Pill connected through a USB-to-UART adapter. It reads newline-delimited JSON at 115200 baud, stores sensor samples and events in SQLite, and sends LED/fan commands back to the board.

## Start

```powershell
cd stm32-monitor
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:STM32_PORT = "COM3"  # Replace with the adapter's COM port
python app.py
```

Open <http://127.0.0.1:5000>. Close any serial monitor first because a COM port can normally be held by only one program. Set `STM32_PORT` to an empty value to run the dashboard without a board; the API and UI will show the disconnected state.

## UART messages

The board sends one JSON object per line, for example:

```json
{"type":"state","temperature":27.4,"smoke_raw":820,"smoke_percent":20,"led1":1,"led2":0,"led3":1,"fan":0,"button1":0,"button2":0}
```

The server sends commands as one JSON object followed by a newline:

```json
{"cmd":"set","led1":1,"led2":0,"led3":1,"fan":70}
```

The sensor fields follow the supplied guide: LM35 temperature in °C and MQ-2 relative ADC percentage. The percentage is not a calibrated gas concentration or a fire safety measurement. Hardware pin assignments and voltage levels must match the firmware and board wiring.

## HTTP API

- `GET /api/state` — latest sample and serial connection status
- `GET /api/history?limit=100` — newest sensor samples in chronological order
- `GET /api/events` — recent serial and control events
- `POST /api/control` — JSON fields `led1`, `led2`, `led3` (0/1) and/or `fan` (0–100)

The SQLite database `monitor.db` is created beside `app.py` on first run.
