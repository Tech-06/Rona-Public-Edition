import os
from pathlib import Path

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def web_search(query: str, max_results: int = 5) -> dict:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"success": False, "error": "TAVILY_API_KEY is not set."}
    try:
        tavily = TavilyClient(api_key=api_key)
        response = tavily.search(
            query=query, search_depth="basic", max_results=max_results
        )
        results = [
            {
                "title": res.get("title", ""),
                "url": res.get("url", ""),
                "content": res.get("content", ""),
            }
            for res in response.get("results", [])
        ]
        return {"success": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
