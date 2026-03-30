from __future__ import annotations
from PIL import Image
import csv
import io
import json
import math
import os
import random
import uuid
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests
from urllib.parse import urlparse
from flask import (Flask, Response, jsonify, render_template, request)

APP_NAME = "FarmPulse"
DEFAULT_TIMEOUT = 14
REPORT_LIMIT = 80

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.secret_key = os.environ.get("SECRET_KEY", "farmpulse-secret-change-me")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FarmPulse/1.0 (+Flask)"})

REPORTS: Dict[str, List[Dict[str, Any]]] = {}
WEATHER_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 15 * 60

DAYS_WINDOW = 16
COMMON_DAILY_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "windspeed_10m_max",
    "shortwave_radiation_sum",
    "reference_evapotranspiration",
]

CROPS = {
    "maize": {
        "days_to_harvest": 90,
        "water": "Moderate water needs; keep moisture steady during flowering and grain fill.",
        "soil": "Well-drained loam or sandy loam",
        "market": "Often strong demand, but prices can dip when many farmers harvest together.",
        "diseases": ["leaf blight", "grey leaf spot", "stalk rot", "armyworm"],
        "fertilizer": "Use a balanced basal fertilizer and top-dress with nitrogen at early growth.",
    },
    "beans": {
        "days_to_harvest": 65,
        "water": "Light but regular watering; avoid standing water.",
        "soil": "Loose, fertile soil with good drainage",
        "market": "Good for early sales before bulk harvests flood local markets.",
        "diseases": ["rust", "anthracnose", "root rot", "angular leaf spot"],
        "fertilizer": "Low nitrogen, more phosphorus and potassium usually works better than heavy nitrogen.",
    },
    "tomato": {
        "days_to_harvest": 75,
        "water": "Deep watering several times a week, more in hot weather.",
        "soil": "Rich soil with calcium support and excellent drainage",
        "market": "High value crop, but supply can be crowded in peak season.",
        "diseases": ["early blight", "late blight", "bacterial wilt", "leaf curl virus"],
        "fertilizer": "Use compost plus calcium support and split feeding to avoid blossom-end rot.",
    },
    "potato": {
        "days_to_harvest": 100,
        "water": "Consistent moisture, then reduce water before harvest.",
        "soil": "Loose sandy loam",
        "market": "Very marketable, but oversupply can lower prices quickly.",
        "diseases": ["late blight", "early blight", "bacterial wilt", "scab"],
        "fertilizer": "Needs potassium and balanced nutrition; avoid excessive nitrogen.",
    },
    "cabbage": {
        "days_to_harvest": 85,
        "water": "Regular watering keeps heads firm.",
        "soil": "Nitrogen-rich but well-drained soil",
        "market": "Stable demand, but common planting cycles can create price pressure.",
        "diseases": ["black rot", "clubroot", "downy mildew", "aphids"],
        "fertilizer": "Provide nitrogen early, then reduce after head formation.",
    },
    "rice": {
        "days_to_harvest": 120,
        "water": "Needs reliable water; paddy systems may require standing water.",
        "soil": "Clay or silty paddy soil",
        "market": "Usually steady demand; grain quality matters for millers and traders.",
        "diseases": ["blast", "sheath blight", "brown spot", "stem borer"],
        "fertilizer": "Split nitrogen applications and keep potassium available.",
    },
    "sorghum": {
        "days_to_harvest": 110,
        "water": "Low to moderate; drought tolerant once established.",
        "soil": "Well-drained soil with moderate fertility",
        "market": "Useful in dry areas and often lower risk than vegetables.",
        "diseases": ["anthracnose", "charcoal rot", "smut", "shoot fly"],
        "fertilizer": "A modest nitrogen program is enough in many fields.",
    },
    "cassava": {
        "days_to_harvest": 240,
        "water": "Low after establishment, but needs moisture at planting.",
        "soil": "Sandy loam or loam",
        "market": "Food-security crop with less price pressure than many short-cycle crops.",
        "diseases": ["cassava mosaic", "bacterial blight", "mealybug", "root rot"],
        "fertilizer": "Use organic matter and potassium-rich feeding where available.",
    },
    "onion": {
        "days_to_harvest": 110,
        "water": "Even moisture early, then dry-down near maturity.",
        "soil": "Loose, well-drained soil with good organic matter",
        "market": "Good market when timed away from mass harvest periods.",
        "diseases": ["purple blotch", "downy mildew", "thrips", "basal rot"],
        "fertilizer": "Balanced feeding with sulfur and potassium support can help bulb quality.",
    },
    "pepper": {
        "days_to_harvest": 85,
        "water": "Regular moisture; avoid water stress.",
        "soil": "Fertile, well-drained soil",
        "market": "Can earn good returns if disease pressure is managed.",
        "diseases": ["powdery mildew", "anthracnose", "bacterial spot", "mites"],
        "fertilizer": "Use moderate nitrogen and good potassium for fruiting.",
    },
}

REGION_RISKS = {
    "humid": ["downy mildew", "leaf spot", "bacterial wilt", "anthracnose", "blight"],
    "dry": ["spider mites", "powdery mildew", "heat stress", "thrips", "leaf scorch"],
    "cold": ["fungal rot", "slow growth", "nutrient lockout", "root stress", "damping off"],
    "default": ["aphids", "powdery mildew", "early blight", "fungal leaf spot", "root rot"],
}

AREA_HINTS = {
    "coastal": "humid",
    "lake": "humid",
    "river": "humid",
    "highland": "cold",
    "mountain": "cold",
    "semi-arid": "dry",
    "arid": "dry",
    "dry": "dry",
    "humid": "humid",
    "cold": "cold",
}

WEATHER_SUMMARY_CODES = {
    "storm": "heavy rain or storm risk",
    "wet": "wet and cloudy",
    "showers": "showery conditions",
    "balanced": "balanced growing weather",
    "hot": "hot and dry conditions",
    "cool": "cool conditions",
}


def icon_svg(name: str) -> str:
    svgs = {
        "weather": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M6 18h11a4 4 0 0 0 .4-7.98A5.5 5.5 0 0 0 6.1 8.6 3.8 3.8 0 0 0 6 18Z'/></svg>",
        "plant": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 22c0-5 1-8 4-11 2-2 4-3 6-3-1 5-3 8-6 10-1 1-2 2-4 4ZM12 22c0-4-1-7-4-10-2-2-4-3-6-3 1 4 3 7 6 9 1 1 2 2 4 4Z'/><path d='M12 22V10'/></svg>",
        "soil": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M3 16h18v4H3z'/><path d='M5 12h14v3H5z'/><path d='M7 7h10v4H7z'/></svg>",
        "chat": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 5h16v11H9l-5 4V5z'/></svg>",
        "report": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M7 3h8l4 4v14H7z'/><path d='M15 3v5h5'/></svg>",
        "irrigation": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 2s6 6 6 11a6 6 0 0 1-12 0c0-5 6-11 6-11z'/></svg>",
        "disease": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 2l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z'/></svg>",
        "market": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7h16l-1 4H5z'/><path d='M6 11v10h12V11'/><path d='M9 21v-6h6v6'/></svg>",
        "sprout": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 21V11'/><path d='M12 11c0-4 2-7 7-8-1 5-4 7-7 8Z'/><path d='M12 11c0-4-2-7-7-8 1 5 4 7 7 8Z'/></svg>",
        "download": "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3v10'/><path d='m8 9 4 4 4-4'/><path d='M4 19h16'/></svg>",
    }
    return svgs.get(name, "")


@app.context_processor
def inject_helpers():
    return {"icon": icon_svg, "app_name": APP_NAME}


def client_id() -> str:
    cid = request.cookies.get("client_id")
    return cid or uuid.uuid4().hex


def set_client_cookie(resp: Response) -> Response:
    resp.set_cookie("client_id", client_id(), max_age=60 * 60 * 24 * 365 * 2, samesite="Lax")
    return resp


def push_report(kind: str, payload: Dict[str, Any]) -> None:
    cid = client_id()
    REPORTS.setdefault(cid, [])
    REPORTS[cid].append({
        "kind": kind,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "payload": payload,
    })
    REPORTS[cid] = REPORTS[cid][-REPORT_LIMIT:]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def today() -> date:
    return date.today()


def iso(d: date) -> str:
    return d.isoformat()


def parse_date(text: str) -> date:
    return date.fromisoformat((text or "").strip())


def clamp_date(d: date, lo: date, hi: date) -> date:
    if d < lo:
        return lo
    if d > hi:
        return hi
    return d


def date_mode(target: date) -> str:
    delta = (target - today()).days
    if delta < 0:
        return "history"
    if delta <= DAYS_WINDOW:
        return "forecast"
    return "planning"


@lru_cache(maxsize=256)
def location_label(place: str) -> Tuple[float, float, str]:
    place = (place or "").strip()
    if not place:
        raise ValueError("Enter a place name.")
    try:
        r = SESSION.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1, "language": "en", "format": "json"},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if results:
            row = results[0]
            label = ", ".join([x for x in [row.get("name"), row.get("admin1"), row.get("country")] if x])
            return float(row["latitude"]), float(row["longitude"]), label
    except Exception:
        pass
    seed = abs(hash(place))
    lat = ((seed % 18000) / 100.0) - 90.0
    lon = (((seed // 18000) % 36000) / 100.0) - 180.0
    return round(lat, 4), round(lon, 4), place.title()


def fetch_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = SESSION.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(payload.get("reason") or "Weather API error")
    return payload


def wind_risk(wind: float) -> str:
    if wind >= 50:
        return "Very windy"
    if wind >= 30:
        return "Windy"
    if wind >= 15:
        return "Light breeze"
    return "Calm"


def summary_from_row(row: Dict[str, Any]) -> str:
    tmax = safe_float(row.get("temperature_2m_max"), 0.0)
    tmin = safe_float(row.get("temperature_2m_min"), 0.0)
    rain = safe_float(row.get("rain_sum"), 0.0)
    precip = safe_float(row.get("precipitation_sum"), 0.0)
    wind = safe_float(row.get("windspeed_10m_max"), 0.0)
    score = 0
    if precip >= 15 or rain >= 15:
        score += 3
    elif precip >= 5:
        score += 2
    elif precip >= 1:
        score += 1
    if tmax >= 34:
        score += 2
    if tmax <= 15:
        score += 1
    if wind >= 35:
        score += 1
    if score >= 4:
        return WEATHER_SUMMARY_CODES["storm"]
    if score == 3:
        return WEATHER_SUMMARY_CODES["wet"]
    if score == 2:
        return WEATHER_SUMMARY_CODES["showers"]
    if tmax >= 31 and precip < 1:
        return WEATHER_SUMMARY_CODES["hot"]
    if tmax <= 18 and precip < 1:
        return WEATHER_SUMMARY_CODES["cool"]
    return WEATHER_SUMMARY_CODES["balanced"]


def weather_advice(row: Dict[str, Any]) -> List[str]:
    tmax = safe_float(row.get("temperature_2m_max"), 0.0)
    tmin = safe_float(row.get("temperature_2m_min"), 0.0)
    precip = safe_float(row.get("precipitation_sum"), 0.0)
    rain = safe_float(row.get("rain_sum"), 0.0)
    wind = safe_float(row.get("windspeed_10m_max"), 0.0)
    shortwave = safe_float(row.get("shortwave_radiation_sum"), 0.0)
    advice = []
    if precip >= 8 or rain >= 8:
        advice.append("Drain water away from roots and avoid spraying immediately before or after rain.")
    elif precip < 1 and tmax >= 30:
        advice.append("Irrigate early morning or late evening to cut evaporation loss.")
    else:
        advice.append("Keep normal watering and monitor soil moisture before irrigating again.")
    if wind >= 25:
        advice.append("Tie tall crops and avoid foliar sprays in strong wind.")
    if tmin <= 12:
        advice.append("Protect young seedlings from cold stress at night.")
    if shortwave >= 25 and tmax >= 28:
        advice.append("Expect strong sun stress; mulch and shade sensitive transplants.")
    return advice


def weather_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    tmax = safe_float(row.get("temperature_2m_max"), 0.0)
    tmin = safe_float(row.get("temperature_2m_min"), 0.0)
    precip = safe_float(row.get("precipitation_sum"), 0.0)
    rain = safe_float(row.get("rain_sum"), 0.0)
    snow = safe_float(row.get("snowfall_sum"), 0.0)
    wind = safe_float(row.get("windspeed_10m_max"), 0.0)
    radiation = safe_float(row.get("shortwave_radiation_sum"), 0.0)
    et0 = safe_float(row.get("reference_evapotranspiration"), 0.0)
    return {
        "date": row.get("date"),
        "temperature_2m_max": round(tmax, 1),
        "temperature_2m_min": round(tmin, 1),
        "precipitation_sum": round(precip, 1),
        "rain_sum": round(rain, 1),
        "snowfall_sum": round(snow, 1),
        "windspeed_10m_max": round(wind, 1),
        "shortwave_radiation_sum": round(radiation, 1),
        "reference_evapotranspiration": round(et0, 1),
        "summary": summary_from_row(row),
        "advice": weather_advice(row),
        "wind_note": wind_risk(wind),
    }


def normalize_daily(daily: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    if not daily:
        return []
    dates = daily.get("time") or []
    rows = []
    for i, ds in enumerate(dates):
        row = {"date": ds}
        for field in COMMON_DAILY_FIELDS:
            values = daily.get(field) or []
            row[field] = values[i] if i < len(values) else None
        row["summary"] = summary_from_row(row)
        rows.append(row)
    return rows


def parse_api_series(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    daily = payload.get("daily") or {}
    return [weather_detail(row) for row in normalize_daily(daily)]




def _weather_cache_key(place: str, target: date) -> Tuple[str, str]:
    return (place.strip().lower(), target.isoformat())


def _weather_cache_get(place: str, target: date) -> Optional[Dict[str, Any]]:
    key = _weather_cache_key(place, target)
    entry = WEATHER_CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (datetime.utcnow().timestamp() - ts) > CACHE_TTL_SECONDS:
        WEATHER_CACHE.pop(key, None)
        return None
    return payload


def _weather_cache_set(place: str, target: date, payload: Dict[str, Any]) -> None:
    WEATHER_CACHE[_weather_cache_key(place, target)] = (datetime.utcnow().timestamp(), payload)

def synthetic_series(center: date, place: str, mode: str) -> List[Dict[str, Any]]:
    seed = abs(hash((place.lower(), center.isoformat(), mode))) % (2 ** 32)
    rng = random.Random(seed)
    month = center.month
    base_temp = {1: 22, 2: 23, 3: 24, 4: 23, 5: 22, 6: 21, 7: 20, 8: 21, 9: 22, 10: 23, 11: 23, 12: 22}[month]
    base_rain = {1: 5, 2: 6, 3: 12, 4: 18, 5: 14, 6: 8, 7: 5, 8: 4, 9: 5, 10: 8, 11: 11, 12: 8}[month]
    rows = []
    start = center - timedelta(days=7)
    for i in range(16):
        d = start + timedelta(days=i)
        swing = math.sin((i / 15.0) * math.pi * 2)
        tmax = base_temp + swing * 3 + rng.uniform(-1.5, 2.5)
        tmin = tmax - (6 + rng.uniform(0, 4))
        precip = max(0, base_rain + rng.uniform(-4, 5) + (1 if i % 5 == 0 else 0))
        rain = max(0, precip * (0.8 if precip > 0 else 0))
        snow = 0 if tmax > 2 else max(0, rng.uniform(0, 2))
        wind = max(4, 10 + rng.uniform(-3, 9) + (2 if mode == "planning" else 0))
        shortwave = max(5, 16 + rng.uniform(-4, 6))
        et0 = max(0.5, 3 + rng.uniform(-1, 1.2))
        row = {
            "date": d.isoformat(),
            "temperature_2m_max": round(tmax, 1),
            "temperature_2m_min": round(tmin, 1),
            "precipitation_sum": round(precip, 1),
            "rain_sum": round(rain, 1),
            "snowfall_sum": round(snow, 1),
            "windspeed_10m_max": round(wind, 1),
            "shortwave_radiation_sum": round(shortwave, 1),
            "reference_evapotranspiration": round(et0, 1),
        }
        row["summary"] = summary_from_row(row)
        rows.append(weather_detail(row))
    return rows


def fetch_weather_window(place: str, target: date) -> Dict[str, Any]:
    cached = _weather_cache_get(place, target)
    if cached is not None:
        return cached

    lat, lon, label = location_label(place)
    mode = date_mode(target)
    series = []
    source = ""
    note = ""

    try:
        if mode == "forecast":
            payload = fetch_json(
                "https://api.open-meteo.com/v1/forecast",
                {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": ",".join(COMMON_DAILY_FIELDS),
                    "forecast_days": DAYS_WINDOW,
                    "timezone": "auto",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                },
            )
            series = parse_api_series(payload)
            source = "Open-Meteo forecast"
            note = "Exact daily forecast within the supported 16-day window."
        elif mode == "history":
            start = clamp_date(target - timedelta(days=7), date(1940, 1, 1), today())
            end = clamp_date(target + timedelta(days=8), date(1940, 1, 1), today())
            payload = fetch_json(
                "https://archive-api.open-meteo.com/v1/archive",
                {
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": ",".join(COMMON_DAILY_FIELDS),
                    "models": "best_match",
                    "timezone": "auto",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                },
            )
            series = parse_api_series(payload)
            source = "Open-Meteo historical weather"
            note = "Historical weather from reanalysis data."
        else:
            start = target - timedelta(days=7)
            end = target + timedelta(days=8)
            payload = fetch_json(
                "https://climate-api.open-meteo.com/v1/climate",
                {
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": ",".join(COMMON_DAILY_FIELDS),
                    "models": "EC_Earth3P_HR",
                    "timezone": "auto",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                },
            )
            series = parse_api_series(payload)
            source = "Open-Meteo climate outlook"
            note = "Planning outlook for dates beyond the 16-day forecast window."
    except Exception:
        series = synthetic_series(target, label, mode)
        source = "offline synthetic outlook"
        note = "Could not reach the weather provider, so a local planning fallback was used."

    selected = next((row for row in series if row["date"] == target.isoformat()), series[len(series) // 2] if series else None)
    payload = {
        "place": label,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "target_date": target.isoformat(),
        "mode": mode,
        "source": source,
        "note": note,
        "series": series,
        "selected": selected,
    }
    _weather_cache_set(place, target, payload)
    return payload


def image_stats(image) -> Dict[str, Any]:
    from PIL import Image, ImageFilter, ImageOps, ImageStat
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.autocontrast(image)
    small = image.resize((240, 240))
    px = list(small.getdata())
    total = max(1, len(px))

    greens = 0
    yellows = 0
    browns = 0
    darks = 0
    strong_red = 0
    for r, g, b in px:
        if g >= r * 1.05 and g >= b * 1.05 and g > 55:
            greens += 1
        if r > 160 and g > 120 and b < 150 and abs(r - g) < 70:
            yellows += 1
        if r > 80 and 30 < g < 120 and b < 90 and r > g:
            browns += 1
        if (r + g + b) / 3 < 55:
            darks += 1
        if r > g + 30 and r > b + 20:
            strong_red += 1

    stat = ImageStat.Stat(image)
    mean = stat.mean
    variance = stat.var
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_strength = ImageStat.Stat(edges).mean[0]

    return {
        "green_ratio": greens / total,
        "yellow_ratio": yellows / total,
        "brown_ratio": browns / total,
        "dark_ratio": darks / total,
        "red_ratio": strong_red / total,
        "avg_rgb": [round(x, 1) for x in mean],
        "rgb_variance": [round(x, 1) for x in variance],
        "edge_strength": round(edge_strength, 1),
    }


def plant_health_assessment(stats: Dict[str, Any], crop: str = "") -> Dict[str, Any]:
    green = stats["green_ratio"]
    yellow = stats["yellow_ratio"]
    brown = stats["brown_ratio"]
    dark = stats["dark_ratio"]
    red = stats["red_ratio"]
    score = 100
    score -= int(brown * 120)
    score -= int(yellow * 85)
    score -= int(dark * 50)
    score -= int(red * 30)
    score += int(green * 20)
    score = max(1, min(99, score))

    issues: List[str] = []
    if brown > 0.12:
        issues.append("Possible leaf scorch, fungal spotting, or nutrient stress.")
    if yellow > 0.10:
        issues.append("Possible nitrogen deficiency or poor root uptake.")
    if dark > 0.20:
        issues.append("The leaf looks stressed or shaded; check watering and drainage.")
    if red > 0.08:
        issues.append("Red/brown tint may indicate injury, disease, or sun stress.")
    if not issues:
        issues.append("No major stress pattern detected from the image.")

    crop_key = crop.lower().strip()
    crop_note = ""
    if crop_key in CROPS:
        crop_note = f"Crop-specific note: {crop_key.title()} often needs {CROPS[crop_key]['fertilizer'].lower()}"

    actions = []
    if score >= 75:
        actions.append("Keep current care, monitor the lower leaves, and continue balanced nutrition.")
    elif score >= 55:
        actions.append("Inspect the underside of the leaf, improve watering consistency, and remove badly damaged leaves.")
        actions.append("Check for pests and fungal spots; use an appropriate treatment only if symptoms spread.")
    else:
        actions.append("Isolate the plant if disease is suspected and inspect nearby plants immediately.")
        actions.append("Improve drainage, reduce overwatering, and correct nutrient gaps with a balanced feed.")

    if crop_key in CROPS:
        actions.append(CROPS[crop_key]["fertilizer"])

    detected = "generic leaf"
    confidence = "low"
    if green > 0.45 and brown < 0.15:
        detected = "healthy green leaf"
        confidence = "medium"
    elif yellow > 0.15 and green > 0.20:
        detected = "chlorotic leaf"
        confidence = "medium"
    elif brown > 0.18:
        detected = "stressed leaf"
        confidence = "medium"

    return {
        "healthy": score >= 65,
        "score": score,
        "detected_plant": detected,
        "detection_confidence": confidence,
        "issues": issues,
        "actions": actions,
        "crop_note": crop_note,
        "resolution": "Treat the cause early and revisit after 3 to 5 days.",
        "status": "Healthy" if score >= 65 else "Needs attention",
    }


def soil_assessment(stats: Dict[str, Any], crop: str = "", leaf_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dark = stats["dark_ratio"]
    brown = stats["brown_ratio"]
    green = stats["green_ratio"]
    yellow = stats["yellow_ratio"]
    edge = stats["edge_strength"]
    moisture = 100 - int((dark * 60) + (brown * 50) - (green * 15))
    moisture = max(5, min(95, moisture))

    texture = "fine and compact"
    if edge > 35:
        texture = "coarse or cloddy"
    if dark > 0.35:
        texture = "moist and heavy"
    if brown > 0.25 and dark < 0.20:
        texture = "dry and dusty"

    comments = []
    if moisture < 35:
        comments.append("Soil looks dry; increase irrigation frequency or add mulch.")
    elif moisture > 70:
        comments.append("Soil looks very moist; make sure drainage is strong.")
    else:
        comments.append("Soil moisture looks moderate and workable.")

    if yellow > 0.08 or brown > 0.10:
        comments.append("Surface color suggests organic matter or residue may help.")

    if leaf_stats:
        if leaf_stats["score"] < 65:
            comments.append("The leaf stress and soil condition point to a root-zone or nutrient issue.")
        else:
            comments.append("Leaf and soil look generally aligned for healthy growth.")

    crop_key = crop.lower().strip()
    fertilizer = "Use a balanced fertilizer and add compost if the soil is weak."
    if crop_key in CROPS:
        fertilizer = CROPS[crop_key]["fertilizer"]

    actions = [
        "Take soil from the root zone, not just the surface, for a better reading.",
        fertilizer,
    ]
    if moisture < 35:
        actions.append("Prioritize watering after sunrise and before heat peaks.")
    elif moisture > 70:
        actions.append("Avoid heavy irrigation until the surface begins to dry a little.")

    return {
        "soil_moisture_hint": moisture,
        "texture_hint": texture,
        "comments": comments,
        "fertilizer": fertilizer,
        "actions": actions,
        "status": "Good" if 35 <= moisture <= 70 else "Needs adjustment",
    }


def crop_recommendation(goal: str, condition: str, water: str, market_access: str) -> Dict[str, Any]:
    text = " ".join([goal, condition, water, market_access]).lower()
    suggestions: List[Tuple[str, str]] = []
    if any(k in text for k in ["drought", "dry", "less water"]):
        suggestions.append(("sorghum", "Drought-tolerant and safer in dry zones."))
        suggestions.append(("cassava", "Stays productive with lower water pressure once established."))
    if any(k in text for k in ["fast", "quick"]):
        suggestions.append(("beans", "Relatively quick harvest and simple marketing."))
        suggestions.append(("onion", "Good when you can manage the crop carefully."))
    if any(k in text for k in ["market", "cash", "high value", "profit"]):
        suggestions.append(("tomato", "High value if watering and disease control are strong."))
        suggestions.append(("pepper", "Strong value crop for disciplined growers."))
    if any(k in text for k in ["food", "security", "staple"]):
        suggestions.append(("cassava", "Reliable food-security crop."))
        suggestions.append(("maize", "A familiar staple for many markets."))
    if any(k in text for k in ["wet", "humid"]):
        suggestions.append(("rice", "Fits wetter systems and more reliable water."))
        suggestions.append(("cabbage", "Can do well with careful drainage."))
    if not suggestions:
        suggestions = [("maize", "Balanced default crop for general use."), ("beans", "Good secondary choice if you want a quicker return.")]

    # de-duplicate while keeping order
    seen = set()
    unique = []
    for crop, reason in suggestions:
        if crop not in seen:
            seen.add(crop)
            unique.append({"crop": crop, "reason": reason, **CROPS.get(crop, {})})
    return {"recommendations": unique[:4], "summary": "Matched to your goal, water supply, and market access."}


def disease_advice(area: str, crop: str) -> Dict[str, Any]:
    area_l = (area or "").lower()
    region = "default"
    for key, val in AREA_HINTS.items():
        if key in area_l:
            region = val
            break
    crop_key = crop.lower().strip()
    diseases = list(CROPS.get(crop_key, {}).get("diseases", []))
    for item in REGION_RISKS[region]:
        if item not in diseases:
            diseases.append(item)
    prevention = [
        "Keep leaves dry when possible and avoid overcrowding.",
        "Rotate crops and remove infected debris early.",
        "Use clean seed or transplants and inspect regularly.",
        "Improve drainage if the area stays wet.",
    ]
    if region == "dry":
        prevention.append("Watch for mites and thrips and irrigate consistently.")
    if region == "humid":
        prevention.append("Use wider spacing and treat fungal pressure early.")
    if region == "cold":
        prevention.append("Delay planting until soil temperature improves.")
    return {"region": region, "common_diseases": diseases[:7], "prevention": prevention}


def irrigation_plan(crop: str, planting_date: Optional[str], location: str, soil: str) -> Dict[str, Any]:
    crop_key = crop.lower().strip()
    info = CROPS.get(crop_key, CROPS["maize"])
    start = parse_date(planting_date) if planting_date else today()
    weather = fetch_weather_window(location or "Nairobi, Kenya", start)
    selected = weather["selected"] or {}
    precip = safe_float(selected.get("precipitation_sum"), 0.0)
    tmax = safe_float(selected.get("temperature_2m_max"), 0.0)
    wind = safe_float(selected.get("windspeed_10m_max"), 0.0)
    base_days = 2 if crop_key in ["maize", "sorghum", "cassava"] else 3
    if tmax >= 31:
        base_days = max(1, base_days - 1)
    if precip >= 8:
        base_days += 2
    if wind >= 30:
        base_days = max(1, base_days - 1)
    water_tip = info["water"]
    return {
        "crop": crop_key or "maize",
        "planting_date": start.isoformat(),
        "location": weather["place"],
        "soil": soil,
        "watering_interval_days": base_days,
        "water_tip": water_tip,
        "weather_context": selected,
        "plan": [
            "Water early morning or late evening.",
            "Mulch around the plant to hold moisture.",
            "Reduce irrigation immediately after heavy rain.",
            "Use drip or targeted watering where possible.",
        ],
    }


def market_analysis(crop: str, planting_date: str, location: str, target_date: Optional[str]) -> Dict[str, Any]:
    crop_key = crop.lower().strip()
    info = CROPS.get(crop_key, CROPS["maize"])
    planting = parse_date(planting_date) if planting_date else today()
    harvest = planting + timedelta(days=info["days_to_harvest"])
    target = parse_date(target_date) if target_date else harvest
    timing_gap = (target - harvest).days
    month = target.month
    seasonal_glut = crop_key in {"tomato", "potato", "cabbage", "onion", "beans"} and month in {3, 4, 5, 10, 11}
    score = 70
    if timing_gap > 21:
        score -= 15
    elif timing_gap < -14:
        score -= 12
    if seasonal_glut:
        score -= 18
    if crop_key in {"cassava", "sorghum"}:
        score += 8
    if crop_key in {"tomato", "pepper"}:
        score += 5 if timing_gap >= 0 else -5
    score = max(10, min(95, score))
    message = "Promising market window"
    if score < 45:
        message = "High supply risk or weak timing"
    elif score < 65:
        message = "Mixed market outlook"
    return {
        "crop": crop_key,
        "location": location,
        "planting_date": planting.isoformat(),
        "target_date": target.isoformat(),
        "estimated_harvest_date": harvest.isoformat(),
        "days_to_harvest": info["days_to_harvest"],
        "market_score": score,
        "market_message": message,
        "seasonal_glut_risk": seasonal_glut,
        "advice": [
            f"Market the crop around {harvest.isoformat()} for the best baseline harvest timing.",
            info["market"],
            "Stagger planting if you want to avoid everyone harvesting at the same time.",
            "Check local buyers before planting if you are targeting a strict selling date.",
        ],
    }


def chat_reply(message: str) -> Dict[str, Any]:
    msg = (message or "").strip()
    low = msg.lower()

    if not msg:
        return {"reply": "Send me a message about weather, crops, soil, irrigation, diseases, reports, or market timing.", "mode": "helper"}

    if any(k in low for k in ["weather", "rain", "forecast", "temperature"]):
        return {
            "reply": "Tell me the place and date, and I will give a weather summary with risk and irrigation guidance.",
            "mode": "weather",
        }

    if any(k in low for k in ["leaf", "plant", "crop", "yellow", "brown", "spots", "disease"]):
        return {
            "reply": "Upload a leaf or soil photo on the matching page, then I will analyze it and give next-step advice.",
            "mode": "plant",
        }

    if any(k in low for k in ["irrig", "water"]):
        return {
            "reply": "Irrigation works best when matched to crop type, soil, rain risk, and wind. Open the irrigation page for a tailored plan.",
            "mode": "irrigation",
        }

    if any(k in low for k in ["market", "sell", "price"]):
        return {
            "reply": "Use the market page to compare planting time, harvest date, and oversupply risk before you commit.",
            "mode": "market",
        }

    if any(k in low for k in ["report", "download"]):
        return {
            "reply": "Open the report page to view recent results and download them as a file.",
            "mode": "report",
        }

    # general farm assistant style answer
    if any(k in low for k in ["hello", "hi", "hey"]):
        return {"reply": "Hello. I can help with weather, plant photos, soil photos, irrigation, disease risk, crop choices, and market timing.", "mode": "greeting"}

    # broad guidance fallback
    if any(k in low for k in ["what", "how", "why", "when", "should", "can", "best"]):
        return {
            "reply": "Give me the crop, place, and date if the question is farm-related. I will turn it into a practical recommendation.",
            "mode": "clarify",
        }

    return {
        "reply": "I did not catch a farm-specific intent, but I can still help with weather, crops, soil, irrigation, diseases, and market timing.",
        "mode": "helper",
    }


def records_for_current_client() -> List[Dict[str, Any]]:
    return REPORTS.get(client_id(), [])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/weather")
def weather_page():
    return render_template("weather.html")


@app.route("/plant")
def plant_page():
    return render_template("plant.html")


@app.route("/soil")
def soil_page():
    return render_template("soil.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/report")
def report_page():
    return render_template("report.html")


@app.route("/irrigation")
def irrigation_page():
    return render_template("irrigation.html")


@app.route("/diseases")
def diseases_page():
    return render_template("diseases.html")


@app.route("/recommendations")
def recommendations_page():
    return render_template("recommendations.html")


@app.route("/market")
def market_page():
    return render_template("market.html")


@app.route("/api/weather")
def api_weather():
    place = request.args.get("place", "Nairobi, Kenya")
    date_text = request.args.get("date", iso(today()))
    target = parse_date(date_text)
    payload = fetch_weather_window(place, target)
    push_report("weather", payload)
    return jsonify(payload)


@app.route("/api/plant/analyze", methods=["POST"])
def api_plant_analyze():
    crop = request.form.get("plant_name") or request.form.get("crop") or ""
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "Please upload a leaf image."}), 400
    try:
        image = Image.open(f.stream)
        stats = image_stats(image)
        result = plant_health_assessment(stats, crop)
        result["image_stats"] = stats
        result["crop_name"] = crop or "Not supplied"
        push_report("plant_analysis", result)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"Could not analyze the leaf image: {exc}"}), 400


@app.route("/api/soil/analyze", methods=["POST"])
def api_soil_analyze():
    crop = request.form.get("crop") or ""
    location = request.form.get("location") or "Nairobi, Kenya"
    soil_file = request.files.get("soil_image")
    if not soil_file:
        return jsonify({"error": "Please upload a soil image."}), 400
    try:
        soil_img = Image.open(soil_file.stream)
        soil_stats = image_stats(soil_img)
        leaf_stats = None
        leaf_file = request.files.get("leaf_image")
        if leaf_file:
            leaf_img = Image.open(leaf_file.stream)
            leaf_stats = image_stats(leaf_img)
        result = soil_assessment(soil_stats, crop, leaf_stats)
        result["location"] = location
        result["crop_name"] = crop or "Not supplied"
        result["soil_stats"] = soil_stats
        if leaf_stats:
            result["leaf_stats"] = leaf_stats
        result["combined_note"] = "Leaf and soil were checked together for a stronger field-level reading." if leaf_stats else "Add a leaf image next time for a stronger comparison."
        push_report("soil_analysis", result)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"Could not analyze the soil image: {exc}"}), 400


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message", "")
    result = chat_reply(msg)
    push_report("chat", {"message": msg, **result})
    return jsonify(result)


@app.route("/api/recommendations", methods=["POST"])
def api_recommendations():
    data = request.get_json(force=True, silent=True) or {}
    goal = data.get("goal", "")
    condition = data.get("condition", "")
    water = data.get("water", "")
    market_access = data.get("market_access", "")
    result = crop_recommendation(goal, condition, water, market_access)
    result.update({"goal": goal, "condition": condition, "water": water, "market_access": market_access})
    push_report("recommendation", result)
    return jsonify(result)


@app.route("/api/diseases")
def api_diseases():
    area = request.args.get("area", "")
    crop = request.args.get("crop", "")
    result = disease_advice(area, crop)
    result.update({"area": area, "crop": crop})
    push_report("disease_risk", result)
    return jsonify(result)


@app.route("/api/irrigation", methods=["POST"])
def api_irrigation():
    data = request.get_json(force=True, silent=True) or {}
    crop = data.get("crop", "")
    planting_date = data.get("planting_date")
    location = data.get("location", "Nairobi, Kenya")
    soil = data.get("soil", "")
    result = irrigation_plan(crop, planting_date, location, soil)
    push_report("irrigation", result)
    return jsonify(result)


@app.route("/api/market", methods=["POST"])
def api_market():
    data = request.get_json(force=True, silent=True) or {}
    crop = data.get("crop", "maize")
    planting_date = data.get("planting_date", iso(today()))
    location = data.get("location", "")
    target_date = data.get("target_date")
    result = market_analysis(crop, planting_date, location, target_date)
    push_report("market", result)
    return jsonify(result)


@app.route("/api/report/latest")
def api_report_latest():
    records = records_for_current_client()
    return jsonify({"records": records})


@app.route("/api/report/download")
def api_report_download():
    records = records_for_current_client()
    fmt = (request.args.get("format") or "csv").lower()
    if fmt == "json":
        payload = json.dumps({"app": APP_NAME, "records": records}, indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="farmpulse-report.json"'},
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["kind", "timestamp", "payload_json"])
    for rec in records:
        writer.writerow([rec.get("kind", ""), rec.get("timestamp", ""), json.dumps(rec.get("payload", {}), ensure_ascii=False)])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="farmpulse-report.csv"'},
    )


@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")


@app.route("/service-worker.js")
def service_worker():
    return app.send_static_file("service-worker.js")



def build_ping_ack(source: str = "pulse_receiver", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ack: Dict[str, Any] = {
        "received": True,
        "source": source,
        "received_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "app": APP_NAME,
    }
    if payload:
        ack["payload"] = payload
    return ack


def forward_ping_ack(callback_url: str, ack: Dict[str, Any]) -> Dict[str, Any]:
    parsed = urlparse(callback_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("callback_url must be a valid http(s) URL")
    resp = SESSION.post(callback_url, json=ack, timeout=DEFAULT_TIMEOUT)
    return {"status_code": resp.status_code, "ok": resp.ok}


@app.route("/health")
def health():
    return "OK", 200


@app.route("/api/ping", methods=["GET", "POST"])
@app.route("/pulse_receiver", methods=["GET", "POST"])
def pulse_receiver():
    payload: Dict[str, Any] = {}
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
    else:
        payload = {k: v for k, v in request.args.items()}
    ack = build_ping_ack("pulse_receiver", payload)

    callback_url = (payload.get("callback_url") or payload.get("reply_to") or request.args.get("callback_url") or request.args.get("reply_to") or "").strip()
    if callback_url:
        try:
            ack["callback"] = forward_ping_ack(callback_url, ack)
        except Exception as exc:
            ack["callback_error"] = str(exc)

    push_report("ping", ack)
    return jsonify(ack), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, use_reloader=False) 
