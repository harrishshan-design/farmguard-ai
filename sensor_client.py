"""Small, dependency-free client for sending sensor readings to FarmGuard.

Use ``send_reading`` from your Raspberry Pi / gateway code, or run this file
directly to verify the connection before wiring physical sensors.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def send_reading(
    server: str,
    *,
    device_id: str,
    token: str,
    zone_id: str,
    moisture: float,
    temperature: float,
    humidity: float,
    light: float,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Validate and POST one reading; returns FarmGuard's decision."""
    payload = {
        "device_id": device_id,
        "token": token,
        "zone_id": zone_id,
        "moisture": moisture,
        "temperature": temperature,
        "humidity": humidity,
        "light": light,
    }
    endpoint = f"{server.rstrip('/')}/api/telemetry"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FarmGuard rejected the reading ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach FarmGuard at {endpoint}: {error.reason}") from error


def read_sensors(args: argparse.Namespace) -> dict[str, float]:
    """Replace this body with GPIO/I2C/serial reads for your sensor board."""
    return {
        "moisture": args.moisture,
        "temperature": args.temperature,
        "humidity": args.humidity,
        "light": args.light,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send sensor readings to FarmGuard AI")
    parser.add_argument("--server", default=os.getenv("FARMGUARD_SERVER", "http://127.0.0.1:7860"))
    parser.add_argument("--device-id", default=os.getenv("FARMGUARD_DEVICE_ID", "esp32-field-01"))
    parser.add_argument("--token", default=os.getenv("FARMGUARD_TOKEN", "farmguard-demo-01"))
    parser.add_argument("--zone-id", default=os.getenv("FARMGUARD_ZONE_ID", "zone-a"))
    parser.add_argument("--moisture", type=float, default=42.0)
    parser.add_argument("--temperature", type=float, default=29.0)
    parser.add_argument("--humidity", type=float, default=65.0)
    parser.add_argument("--light", type=float, default=70.0)
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between readings")
    parser.add_argument("--once", action="store_true", help="Send one reading and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    while True:
        values = read_sensors(args)
        result = send_reading(
            args.server,
            device_id=args.device_id,
            token=args.token,
            zone_id=args.zone_id,
            **values,
        )
        print(json.dumps(result, indent=2))
        if args.once:
            return
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()
