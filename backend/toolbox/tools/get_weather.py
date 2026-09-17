import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def get_weather(city: str) -> dict:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return {"success": False, "error": "OPENWEATHER_API_KEY is not set."}

    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    try:
        response = requests.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "weather": data["weather"][0]["description"],
            "temperature_celsius": data["main"]["temp"],
            "humidity": data["main"]["humidity"],
            "city": data["name"],
            "country": data["sys"]["country"],
        }
    except requests.exceptions.RequestException as exc:
        return {"success": False, "error": str(exc)}
    except (KeyError, IndexError) as exc:
        return {"success": False, "error": f"Error parsing weather data: {exc}"}
