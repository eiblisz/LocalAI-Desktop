from datetime import datetime

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_VARIABLES = ",".join([
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "is_day",
])

HOURLY_VARIABLES = ",".join([
    "temperature_2m",
    "precipitation_probability",
    "weather_code",
    "cloud_cover",
])


class WeatherToolError(RuntimeError):
    pass


def geocode_location(location, timeout=15.0):
    clean = " ".join(str(location).strip().split())
    if not clean:
        raise WeatherToolError("A location is required for the Weather tool.")

    response = requests.get(
        GEOCODING_URL,
        params={
            "name": clean,
            "count": 1,
            "format": "json",
            "language": "en",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise WeatherToolError(f"Location not found: {clean}")

    item = results[0]
    return {
        "name": item.get("name", clean),
        "country": item.get("country", ""),
        "admin1": item.get("admin1", ""),
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "timezone": item.get("timezone", "auto"),
    }


def get_weather(location, timeout=20.0):
    geo = geocode_location(location, timeout=timeout)

    response = requests.get(
        FORECAST_URL,
        params={
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "current": CURRENT_VARIABLES,
            "hourly": HOURLY_VARIABLES,
            "forecast_hours": 12,
            "timezone": "auto",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    hourly = payload.get("hourly") or {}
    hourly_units = payload.get("hourly_units") or {}
    times = hourly.get("time") or []
    forecast = []

    for index, stamp in enumerate(times[:12]):
        row = {"time": stamp}
        for key in (
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
            "cloud_cover",
        ):
            values = hourly.get(key) or []
            row[key] = values[index] if index < len(values) else None
            row[f"{key}_unit"] = hourly_units.get(key, "")
        forecast.append(row)

    return {
        "provider": "Open-Meteo",
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "location": geo,
        "timezone": payload.get("timezone", geo.get("timezone", "")),
        "current": payload.get("current") or {},
        "current_units": payload.get("current_units") or {},
        "next_12_hours": forecast,
    }


def weather_context_text(weather):
    location = weather.get("location") or {}
    current = weather.get("current") or {}
    units = weather.get("current_units") or {}

    place = ", ".join(
        value
        for value in (
            location.get("name", ""),
            location.get("admin1", ""),
            location.get("country", ""),
        )
        if value
    )

    lines = [
        "WEATHER TOOL DATA",
        f"Provider: {weather.get('provider', 'Open-Meteo')}",
        f"Retrieved: {weather.get('retrieved_at', '')}",
        f"Location: {place}",
        f"Latitude: {location.get('latitude', '')}",
        f"Longitude: {location.get('longitude', '')}",
        f"Timezone: {weather.get('timezone', '')}",
        "",
        "CURRENT CONDITIONS",
    ]

    labels = [
        ("time", "Time"),
        ("temperature_2m", "Temperature"),
        ("apparent_temperature", "Apparent temperature"),
        ("relative_humidity_2m", "Relative humidity"),
        ("precipitation", "Precipitation"),
        ("rain", "Rain"),
        ("snowfall", "Snowfall"),
        ("weather_code", "Weather code"),
        ("cloud_cover", "Cloud cover"),
        ("wind_speed_10m", "Wind speed"),
        ("wind_gusts_10m", "Wind gusts"),
        ("is_day", "Is day"),
    ]
    for key, label in labels:
        value = current.get(key)
        if value is None:
            continue
        unit = units.get(key, "")
        lines.append(f"{label}: {value}{(' ' + unit) if unit else ''}")

    lines.extend(["", "NEXT 12 HOURS"])
    for row in weather.get("next_12_hours") or []:
        lines.append(
            "{time} | temp={temp}{temp_unit} | precip_prob={prob}{prob_unit} "
            "| cloud={cloud}{cloud_unit} | weather_code={code}".format(
                time=row.get("time", ""),
                temp=row.get("temperature_2m", ""),
                temp_unit=row.get("temperature_2m_unit", ""),
                prob=row.get("precipitation_probability", ""),
                prob_unit=row.get("precipitation_probability_unit", ""),
                cloud=row.get("cloud_cover", ""),
                cloud_unit=row.get("cloud_cover_unit", ""),
                code=row.get("weather_code", ""),
            )
        )

    return "\n".join(lines)
