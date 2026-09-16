import pytest

from app import weather_tool


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_weather_tool_uses_geocoding_then_forecast(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        if "geocoding-api" in url:
            return FakeResponse({
                "results": [{
                    "name": "Bad Nenndorf",
                    "country": "Germany",
                    "admin1": "Lower Saxony",
                    "latitude": 52.34,
                    "longitude": 9.38,
                    "timezone": "Europe/Berlin",
                }]
            })
        return FakeResponse({
            "timezone": "Europe/Berlin",
            "current": {
                "time": "2026-09-16T14:00",
                "temperature_2m": 18.2,
                "cloud_cover": 75,
                "weather_code": 3,
            },
            "current_units": {
                "temperature_2m": "C",
                "cloud_cover": "%",
            },
            "hourly": {
                "time": ["2026-09-16T14:00", "2026-09-16T15:00"],
                "temperature_2m": [18.2, 18.0],
                "precipitation_probability": [10, 20],
                "weather_code": [3, 3],
                "cloud_cover": [75, 80],
            },
            "hourly_units": {
                "temperature_2m": "C",
                "precipitation_probability": "%",
                "cloud_cover": "%",
            },
        })

    monkeypatch.setattr(weather_tool.requests, "get", fake_get)

    result = weather_tool.get_weather("Bad Nenndorf, Germany")
    text = weather_tool.weather_context_text(result)

    assert result["provider"] == "Open-Meteo"
    assert result["location"]["name"] == "Bad Nenndorf"
    assert "Temperature: 18.2 C" in text
    assert "Cloud cover: 75 %" in text
    assert len(calls) == 2
    assert calls[1][1]["forecast_hours"] == 12


def test_weather_tool_rejects_unknown_location(monkeypatch):
    monkeypatch.setattr(
        weather_tool.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({"results": []}),
    )

    with pytest.raises(weather_tool.WeatherToolError):
        weather_tool.geocode_location("NoSuchPlace")
