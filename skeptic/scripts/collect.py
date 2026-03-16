#!/usr/bin/env python3
"""
Skeptic Weather Accuracy Tracker
Collects forecast predictions and ground-truth sensor readings,
then computes accuracy scores.

Usage:
    python collect.py govee          # Poll Govee sensor, record temp
    python collect.py forecasts      # Capture tomorrow's forecasts from all sources
    python collect.py actuals        # Compute yesterday's actual high/low and score predictions
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

# Location (set via environment or defaults)
LAT = float(os.environ.get("SKEPTIC_LAT", "44.35199"))
LON = float(os.environ.get("SKEPTIC_LON", "-121.44685"))
LOCATION_NAME = os.environ.get("SKEPTIC_LOCATION", "Sisters, OR")
TIMEZONE = os.environ.get("SKEPTIC_TZ", "America/Los_Angeles")

# API Keys (from environment / GitHub secrets)
GOVEE_API_KEY = os.environ.get("GOVEE_API_KEY", "")
GOVEE_DEVICE_MAC = os.environ.get("GOVEE_DEVICE_MAC", "")
GOVEE_DEVICE_SKU = os.environ.get("GOVEE_DEVICE_SKU", "")
OWM_API_KEY = os.environ.get("OWM_API_KEY", "")
WEATHERAPI_KEY = os.environ.get("WEATHERAPI_KEY", "")
PIRATE_KEY = os.environ.get("PIRATE_KEY", "")

# Data directory (relative to repo root)
DATA_DIR = Path(__file__).parent.parent / "data"


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list:
    """Load JSON file, return empty dict if missing."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data):
    """Save data as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  Saved: {path}")


def api_get(url: str, headers: dict = None) -> dict:
    """Make a GET request and return parsed JSON."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} from {url}")
        return {}
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return {}


def api_post(url: str, body: dict, headers: dict = None) -> dict:
    """Make a POST request with JSON body and return parsed JSON."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} from {url}")
        return {}
    except Exception as e:
        print(f"  Error posting {url}: {e}")
        return {}


def today_str() -> str:
    """Today's date as YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    """Yesterday's date as YYYY-MM-DD."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def tomorrow_str() -> str:
    """Tomorrow's date as YYYY-MM-DD."""
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


# ── Govee Polling ─────────────────────────────────────────────────────────────

def poll_govee():
    """Read current temperature from Govee sensor and append to readings file."""
    print("Polling Govee sensor...")

    if not all([GOVEE_API_KEY, GOVEE_DEVICE_MAC, GOVEE_DEVICE_SKU]):
        print("  Missing Govee credentials (API key, MAC, or SKU). Skipping.")
        return

    url = "https://openapi.api.govee.com/router/api/v1/device/state"
    body = {
        "requestId": "skeptic-poll",
        "payload": {
            "sku": GOVEE_DEVICE_SKU,
            "device": GOVEE_DEVICE_MAC
        }
    }
    headers = {
        "Govee-API-Key": GOVEE_API_KEY,
        "Accept": "application/json"
    }

    resp = api_post(url, body, headers)

    if not resp:
        print("  No response from Govee API.")
        return

    # Parse temperature from response
    # Govee OpenAPI v2 uses "instance": "sensorTemperature" and returns °F directly
    temp_f = None
    try:
        capabilities = resp.get("payload", {}).get("capabilities", [])
        for cap in capabilities:
            instance = cap.get("instance", "")
            if instance == "online":
                if not cap.get("state", {}).get("value"):
                    print("  Govee device is offline.")
                    return
            if instance == "sensorTemperature":
                # OpenAPI v2 returns temperature in Fahrenheit directly
                val = cap.get("state", {}).get("value")
                if val is not None:
                    temp_f = float(val)
    except Exception as e:
        print(f"  Error parsing Govee response: {e}")
        print(f"  Raw response: {json.dumps(resp)[:500]}")
        return

    if temp_f is None:
        print("  Could not find temperature in Govee response.")
        print(f"  Raw response: {json.dumps(resp)[:500]}")
        return

    temp_f = round(temp_f, 1)
    now = datetime.now(timezone.utc).isoformat()
    print(f"  Govee temp: {temp_f} F at {now}")

    # Append to readings file
    readings_file = DATA_DIR / "sensor-readings.json"
    readings = load_json(readings_file)
    if not isinstance(readings, dict):
        readings = {}

    date_key = today_str()
    if date_key not in readings:
        readings[date_key] = []

    readings[date_key].append({
        "temp_f": temp_f,
        "timestamp": now
    })

    # Prune readings older than 90 days
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    readings = {k: v for k, v in readings.items() if k >= cutoff}

    save_json(readings_file, readings)
    print(f"  Recorded. {len(readings[date_key])} readings today.")


# ── Forecast Collection ───────────────────────────────────────────────────────

def fetch_open_meteo(target_date: str) -> dict | None:
    """Fetch forecast from Open-Meteo (free, no key needed)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&timezone=auto&forecast_days=3"
    )
    data = api_get(url)
    if not data or "daily" not in data:
        return None

    daily = data["daily"]
    dates = daily.get("time", [])
    if target_date not in dates:
        return None

    idx = dates.index(target_date)
    return {
        "source": "Open-Meteo",
        "high": round(daily["temperature_2m_max"][idx], 1),
        "low": round(daily["temperature_2m_min"][idx], 1),
        "precip": round(daily.get("precipitation_sum", [0])[idx] or 0, 2),
        "wind": round(daily.get("wind_speed_10m_max", [0])[idx] or 0, 1)
    }


def fetch_nws_forecast(target_date: str) -> dict | None:
    """Fetch forecast from NWS (free, no key needed, US only)."""
    # Step 1: Get grid point
    points_url = f"https://api.weather.gov/points/{LAT},{LON}"
    headers = {"User-Agent": "SkepticWeather/1.0 (support@hogbodylabs.com)"}
    points = api_get(points_url, headers)
    if not points:
        return None

    forecast_url = points.get("properties", {}).get("forecast")
    if not forecast_url:
        return None

    # Step 2: Get forecast
    forecast = api_get(forecast_url, headers)
    if not forecast:
        return None

    periods = forecast.get("properties", {}).get("periods", [])
    if not periods:
        return None

    # Find the daytime period for target date
    high = None
    low = None
    wind = None
    for period in periods:
        start = period.get("startTime", "")[:10]
        if start == target_date:
            temp = period.get("temperature")
            if period.get("isDaytime"):
                high = temp
                wind_str = period.get("windSpeed", "0 mph")
                try:
                    wind = float(wind_str.split()[0])
                except (ValueError, IndexError):
                    wind = 0
            else:
                low = temp

    if high is None:
        return None

    return {
        "source": "NWS",
        "high": high,
        "low": low,
        "precip": 0,  # NWS doesn't give numeric precip in this endpoint
        "wind": wind or 0
    }


def fetch_owm(target_date: str) -> dict | None:
    """Fetch forecast from OpenWeatherMap."""
    if not OWM_API_KEY:
        return None

    url = (
        f"https://api.openweathermap.org/data/3.0/onecall"
        f"?lat={LAT}&lon={LON}&exclude=minutely,hourly,alerts"
        f"&units=imperial&appid={OWM_API_KEY}"
    )
    data = api_get(url)
    if not data or "daily" not in data:
        return None

    for day in data["daily"]:
        dt = datetime.fromtimestamp(day["dt"]).strftime("%Y-%m-%d")
        if dt == target_date:
            return {
                "source": "OWM",
                "high": round(day["temp"]["max"], 1),
                "low": round(day["temp"]["min"], 1),
                "precip": round(day.get("rain", 0) / 25.4, 2) if isinstance(day.get("rain"), (int, float)) else 0,
                "wind": round(day.get("wind_speed", 0), 1)
            }
    return None


def fetch_weatherapi(target_date: str) -> dict | None:
    """Fetch forecast from WeatherAPI.com."""
    if not WEATHERAPI_KEY:
        return None

    url = (
        f"https://api.weatherapi.com/v1/forecast.json"
        f"?key={WEATHERAPI_KEY}&q={LAT},{LON}&days=3&aqi=no"
    )
    data = api_get(url)
    if not data or "forecast" not in data:
        return None

    for day in data["forecast"].get("forecastday", []):
        if day.get("date") == target_date:
            d = day["day"]
            return {
                "source": "WeatherAPI",
                "high": round(d["maxtemp_f"], 1),
                "low": round(d["mintemp_f"], 1),
                "precip": round(d.get("totalprecip_in", 0), 2),
                "wind": round(d.get("maxwind_mph", 0), 1)
            }
    return None


def fetch_pirate(target_date: str) -> dict | None:
    """Fetch forecast from Pirate Weather."""
    if not PIRATE_KEY:
        return None

    url = (
        f"https://api.pirateweather.net/forecast"
        f"/{PIRATE_KEY}/{LAT},{LON}"
        f"?units=us&exclude=minutely,flags"
    )
    data = api_get(url)
    if not data or "daily" not in data:
        return None

    for day in data["daily"].get("data", []):
        dt = datetime.fromtimestamp(day["time"]).strftime("%Y-%m-%d")
        if dt == target_date:
            return {
                "source": "Pirate",
                "high": round(day.get("temperatureHigh", 0), 1),
                "low": round(day.get("temperatureLow", 0), 1),
                "precip": round(day.get("precipAccumulation", 0), 2),
                "wind": round(day.get("windSpeed", 0), 1)
            }
    return None


def fetch_met_norway(target_date: str) -> dict | None:
    """Fetch forecast from MET Norway (free, no key needed)."""
    url = (
        f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
        f"?lat={LAT:.4f}&lon={LON:.4f}"
    )
    headers = {"User-Agent": "SkepticWeather/1.0 (support@hogbodylabs.com)"}
    data = api_get(url, headers)
    if not data or "properties" not in data:
        return None

    timeseries = data["properties"].get("timeseries", [])
    if not timeseries:
        return None

    # MET Norway gives hourly data; compute daily high/low
    temps = []
    winds = []
    for entry in timeseries:
        t = entry.get("time", "")[:10]
        if t == target_date:
            details = entry.get("data", {}).get("instant", {}).get("details", {})
            temp_c = details.get("air_temperature")
            wind_ms = details.get("wind_speed")
            if temp_c is not None:
                temps.append(temp_c * 9 / 5 + 32)  # Convert to F
            if wind_ms is not None:
                winds.append(wind_ms * 2.237)  # Convert m/s to mph

    if not temps:
        return None

    return {
        "source": "MET Norway",
        "high": round(max(temps), 1),
        "low": round(min(temps), 1),
        "precip": 0,
        "wind": round(max(winds) if winds else 0, 1)
    }


def collect_forecasts():
    """Collect tomorrow's forecasts from all sources."""
    target = tomorrow_str()
    print(f"Collecting forecasts for {target}...")

    fetchers = [
        ("Open-Meteo", fetch_open_meteo),
        ("NWS", fetch_nws_forecast),
        ("OWM", fetch_owm),
        ("WeatherAPI", fetch_weatherapi),
        ("Pirate", fetch_pirate),
        ("MET Norway", fetch_met_norway),
    ]

    predictions = []
    for name, fetcher in fetchers:
        print(f"  Fetching {name}...")
        try:
            result = fetcher(target)
            if result:
                predictions.append(result)
                print(f"    Hi: {result['high']} Lo: {result['low']}")
            else:
                print(f"    No data returned.")
        except Exception as e:
            print(f"    Error: {e}")

    if not predictions:
        print("  No forecasts collected. Skipping save.")
        return

    forecast_data = {
        "forecastDate": target,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "location": LOCATION_NAME,
        "latitude": LAT,
        "longitude": LON,
        "predictions": predictions
    }

    forecast_file = DATA_DIR / "forecasts" / f"{target}.json"
    save_json(forecast_file, forecast_data)
    print(f"  Collected {len(predictions)} sources for {target}.")


# ── Actuals Computation ───────────────────────────────────────────────────────

def compute_actuals():
    """Compute yesterday's actual high/low from sensor readings and score predictions."""
    yesterday = yesterday_str()
    print(f"Computing actuals for {yesterday}...")

    # Load sensor readings
    readings_file = DATA_DIR / "sensor-readings.json"
    readings = load_json(readings_file)

    if yesterday not in readings or not readings[yesterday]:
        print(f"  No sensor readings for {yesterday}. Skipping.")
        return

    day_readings = readings[yesterday]
    temps = [r["temp_f"] for r in day_readings]
    actual_high = round(max(temps), 1)
    actual_low = round(min(temps), 1)
    num_readings = len(temps)

    print(f"  Actual: Hi {actual_high}, Lo {actual_low} (from {num_readings} readings)")

    # Load forecast for yesterday
    forecast_file = DATA_DIR / "forecasts" / f"{yesterday}.json"
    forecast = load_json(forecast_file)

    if not forecast or "predictions" not in forecast:
        print(f"  No forecast data for {yesterday}. Saving actuals only.")
        daily_result = {
            "date": yesterday,
            "actualHigh": actual_high,
            "actualLow": actual_low,
            "numReadings": num_readings,
            "groundTruth": "Govee sensor",
            "predictions": []
        }
    else:
        # Score each source
        scored = []
        for pred in forecast["predictions"]:
            high_miss = round(pred["high"] - actual_high, 1)
            low_miss = round(pred["low"] - actual_low, 1)
            scored.append({
                "source": pred["source"],
                "predictedHigh": pred["high"],
                "predictedLow": pred["low"],
                "highMiss": high_miss,
                "lowMiss": low_miss,
                "absHighMiss": abs(high_miss),
                "absLowMiss": abs(low_miss)
            })
            print(f"    {pred['source']}: Hi miss {high_miss:+.1f}, Lo miss {low_miss:+.1f}")

        daily_result = {
            "date": yesterday,
            "actualHigh": actual_high,
            "actualLow": actual_low,
            "numReadings": num_readings,
            "groundTruth": "Govee sensor",
            "predictions": scored
        }

    # Save daily result
    daily_file = DATA_DIR / "daily" / f"{yesterday}.json"
    save_json(daily_file, daily_result)

    # Update rolling accuracy scorecard
    update_accuracy(daily_result)

    # Update summary for website
    update_summary()


def update_accuracy(new_result: dict):
    """Update the rolling accuracy scorecard with a new day's results."""
    accuracy_file = DATA_DIR / "accuracy.json"
    accuracy = load_json(accuracy_file)

    if not accuracy:
        accuracy = {
            "location": LOCATION_NAME,
            "groundTruth": "Govee sensor",
            "dailyResults": []
        }

    # Add new result
    # Remove any existing entry for this date (idempotent)
    accuracy["dailyResults"] = [
        r for r in accuracy["dailyResults"]
        if r["date"] != new_result["date"]
    ]
    accuracy["dailyResults"].append(new_result)

    # Sort by date, keep last 90 days
    accuracy["dailyResults"].sort(key=lambda r: r["date"])
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    accuracy["dailyResults"] = [
        r for r in accuracy["dailyResults"] if r["date"] >= cutoff
    ]

    accuracy["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    save_json(accuracy_file, accuracy)


def update_summary():
    """Generate summary.json for the website from accuracy data."""
    accuracy_file = DATA_DIR / "accuracy.json"
    accuracy = load_json(accuracy_file)

    if not accuracy or not accuracy.get("dailyResults"):
        print("  No accuracy data to summarize.")
        return

    results = accuracy["dailyResults"]
    days_with_data = len([r for r in results if r.get("predictions")])

    # Compute per-source stats
    source_stats = {}
    for result in results:
        for pred in result.get("predictions", []):
            src = pred["source"]
            if src not in source_stats:
                source_stats[src] = {
                    "source": src,
                    "highMisses": [],
                    "lowMisses": []
                }
            source_stats[src]["highMisses"].append(pred["absHighMiss"])
            source_stats[src]["lowMisses"].append(pred["absLowMiss"])

    sources = []
    for src, stats in source_stats.items():
        n = len(stats["highMisses"])
        hi_misses = stats["highMisses"]
        lo_misses = stats["lowMisses"]

        sources.append({
            "source": src,
            "daysTracked": n,
            "avgHighMiss": round(sum(hi_misses) / n, 1) if n else 0,
            "avgLowMiss": round(sum(lo_misses) / n, 1) if n else 0,
            "highWithin2": round(100 * sum(1 for m in hi_misses if m <= 2) / n, 0) if n else 0,
            "highWithin5": round(100 * sum(1 for m in hi_misses if m <= 5) / n, 0) if n else 0,
            "lowWithin2": round(100 * sum(1 for m in lo_misses if m <= 2) / n, 0) if n else 0,
            "lowWithin5": round(100 * sum(1 for m in lo_misses if m <= 5) / n, 0) if n else 0,
        })

    # Sort by average overall miss (best first)
    sources.sort(key=lambda s: (s["avgHighMiss"] + s["avgLowMiss"]) / 2)

    # Recent daily results (last 14 days for the website)
    recent = sorted(results, key=lambda r: r["date"], reverse=True)[:14]

    summary = {
        "location": LOCATION_NAME,
        "groundTruth": "Govee sensor",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "dateRange": {
            "start": results[0]["date"] if results else "",
            "end": results[-1]["date"] if results else ""
        },
        "daysWithData": days_with_data,
        "scorecard": sources,
        "recentDays": recent
    }

    summary_file = DATA_DIR / "summary.json"
    save_json(summary_file, summary)
    print(f"  Summary updated: {days_with_data} days, {len(sources)} sources.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python collect.py [govee|forecasts|actuals]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "govee":
        poll_govee()
    elif command == "forecasts":
        collect_forecasts()
    elif command == "actuals":
        compute_actuals()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python collect.py [govee|forecasts|actuals]")
        sys.exit(1)
