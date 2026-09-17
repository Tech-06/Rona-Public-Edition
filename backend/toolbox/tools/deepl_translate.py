import os
from pathlib import Path

import deepl
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def translate_text(text: str, target_lang: str) -> dict:
    api_key = os.getenv("DEEPL_API_KEY")
    if not api_key:
        return {"success": False, "error": "DEEPL_API_KEY is not set."}
    try:
        translator = deepl.Translator(api_key)
        result = translator.translate_text(text, target_lang=target_lang)
        return {
            "success": True,
            "translated_text": result.text,
            "detected_source_lang": result.detected_source_lang,
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
