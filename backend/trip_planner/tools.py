import requests, os
from datetime import datetime, timedelta, timezone
from langchain_core.tools import tool

UA = {"User-Agent": "LangGraph-Demo/1.0 (+https://example.local)"}
meta = {"verbose": True}

@tool("search_tool")
def search_tool(query: str) -> str:
    """Search the web for a concise answer/snippet (Wikipedia→DuckDuckGo fallback)."""
    if meta["verbose"]:
        print("[INFO] search_tool is called. Executing...")
    q = (query or "").strip()
    try:
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(q),
            headers=UA,
            timeout=4,
        )
        if r.status_code == 200:
            data = r.json()
            extract = data.get("extract")
            if extract:
                title = data.get("title", "Wikipedia")
                return f"{title}: {extract}"
    except Exception:
        pass

    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=UA,
            timeout=4,
        )
        if r.status_code == 200:
            data = r.json()
            abstract = data.get("AbstractText")
            if abstract:
                return abstract
            heading = data.get("Heading")
            if heading:
                return heading
    except Exception:
        pass

    return f"[search] No concise result for: {q}. Try rephrasing or a more specific query."


def _parse_date_label(date_label: str) -> str:
    now = datetime.now(timezone.utc)
    dl = (date_label or "today").strip().lower()
    if dl in {"today", "now"}:
        d = now
    elif dl in {"tomorrow", "tmr"}:
        d = now + timedelta(days=1)
    else:
        try:
            d = datetime.fromisoformat(dl).replace(tzinfo=timezone.utc)
        except Exception:
            d = now
    return d.strftime("%Y-%m-%d")


@tool("weather_tool")
def weather_tool(city: str, date: str = "today") -> str:
    """Get simple weather (Open-Meteo). Supports 'today'/'tomorrow' or ISO date."""
    if meta["verbose"]:
        print("[INFO] weather_tool is called. Executing...")

    city_q = (city or "").strip()
    if not city_q:
        return "[weather] Please provide a city name."

    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city_q, "count": 1, "language": "en"},
            headers=UA,
            timeout=4,
        )
        if geo.status_code != 200:
            return f"[weather] Geocoding failed for {city_q}."
        g = geo.json()
        results = g.get("results") or []
        if not results:
            return f"[weather] City not found: {city_q}."
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        canonical = results[0].get("name", city_q)
        country = results[0].get("country", "")

        target = _parse_date_label(date)

        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "UTC",
                "start_date": target,
                "end_date": target,
            },
            headers=UA,
            timeout=4,
        )
        if fc.status_code != 200:
            return f"[weather] Forecast fetch failed for {canonical}."
        d = fc.json()
        daily = d.get("daily", {})
        if not daily.get("time"):
            return f"[weather] No forecast data for {canonical} on {target}."

        tmax = daily.get("temperature_2m_max", [None])[0]
        tmin = daily.get("temperature_2m_min", [None])[0]
        rain = daily.get("precipitation_sum", [None])[0]
        code = daily.get("weathercode", [None])[0]

        desc_map = {
            0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
            45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "drizzle",
            55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
            71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
            81: "heavy showers", 95: "thunderstorm",
        }
        desc = desc_map.get(code, "mixed conditions")
        rain_txt = f", precip {rain}mm" if rain is not None else ""
        return (
            f"Weather in {canonical}{' ('+country+')' if country else ''} on {target}: "
            f"{desc}, min {tmin}°C / max {tmax}°C{rain_txt}."
        )

    except Exception as e:
        return f"[weather] Error: {e}"


@tool("google_search_tool")
def google_search_tool(query: str) -> str:
    """Search Google for a list of snippets using the Custom Search JSON API."""
    if meta["verbose"]:
        print("[INFO] google_search_tool is called. Executing...")

    # 假设环境变量已被设置，因为这个工具已被注入
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query
            },
            headers=UA,
            timeout=4
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])

        if not items:
            return f"[google_search] No results found for: {query}"

        results = []
        for i, item in enumerate(items[:3]):
            title = item.get("title")
            snippet = item.get("snippet", "").replace("\n", "")
            results.append(f"{i+1}. {title}: {snippet}")
        
        return "\n".join(results)

    except Exception as e:
        # 如果 API 密钥失效或服务未启用，请求仍可能失败
        return f"[google_search] API call failed. Error: {e}"


@tool("google_maps_directions_tool")
def google_maps_directions_tool(origin: str, destination: str) -> str:
    """Get travel directions from Google Maps Directions API."""
    if meta["verbose"]:
        print("[INFO] google_maps_directions_tool is called. Executing...")

    # 假设环境变量已被设置
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params={
                "origin": origin,
                "destination": destination,
                "key": GOOGLE_API_KEY,
                "units": "metric"
            },
            headers=UA,
            timeout=4
        )
        r.raise_for_status()
        data = r.json()
        
        if data.get("status") != "OK" or not data.get("routes"):
            return f"[google_maps] Could not find directions from {origin} to {destination}. Status: {data.get('status')}"

        route = data["routes"][0]
        leg = route["legs"][0]
        summary = route.get("summary", "N/A")
        distance = leg["distance"]["text"]
        duration = leg["duration"]["text"]
        
        steps = []
        for i, step in enumerate(leg["steps"][:3]):
            import re
            instructions = re.sub(r'<[^>]+>', '', step["html_instructions"])
            steps.append(f"  {i+1}. {instructions} ({step['distance']['text']})")
        
        steps_summary = "\n".join(steps)
        if len(leg["steps"]) > 3:
            steps_summary += "\n  ..."

        return (
            f"Directions from {origin} to {destination} ({summary}):\n"
            f"Total Distance: {distance}\n"
            f"Total Duration: {duration}\n"
            f"First steps:\n{steps_summary}"
        )

    except Exception as e:
        return f"[google_maps] API call failed. Error: {e}"


# --- 2. 动态构建 TOOLS 列表 ---

# 基础工具 (始终包含)
TOOLS = [search_tool, weather_tool]

# 检查并注入 Google Search Tool
if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
    TOOLS.append(google_search_tool)
    print("✅ Google Search Tool: enabled")
else:
    print("❌ Google Search Tool: disabled (missing GOOGLE_API_KEY or GOOGLE_CSE_ID)")

# 检查并注入 Google Maps Directions Tool
if os.getenv("GOOGLE_API_KEY"):
    TOOLS.append(google_maps_directions_tool)
    print("✅ Google Maps Directions Tool: enabled")
else:
    print("❌ Google Maps Directions Tool: disabled (missing GOOGLE_API_KEY or GOOGLE_CSE_ID)")

print(f"Tools: {[t.name for t in TOOLS]}")