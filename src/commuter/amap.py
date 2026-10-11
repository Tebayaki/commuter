import re
from collections import deque
from threading import Lock
from time import monotonic, sleep

import requests

AMAP_DIRECTION_URL = "https://restapi.amap.com/v3/direction/driving"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REQUEST_RATE_LIMIT = 3
AMAP_REQUEST_RATE_WINDOW = 1.0
_request_starts: deque[float] = deque()
_request_starts_lock = Lock()


def _wait_for_request_slot() -> None:
    """Limit the process to three Amap request starts in every rolling second."""
    while True:
        with _request_starts_lock:
            now = monotonic()
            while (
                _request_starts
                and now - _request_starts[0] >= AMAP_REQUEST_RATE_WINDOW
            ):
                _request_starts.popleft()
            if len(_request_starts) < AMAP_REQUEST_RATE_LIMIT:
                _request_starts.append(now)
                return
            wait_seconds = (
                AMAP_REQUEST_RATE_WINDOW - (now - _request_starts[0])
            )
        sleep(wait_seconds)


def _get_response(url: str, params: dict[str, str]) -> requests.Response:
    """Send a request within Amap's per-second request rate limit."""
    _wait_for_request_slot()
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response


def geocode_address(address: str, amap_key: str, city: str = "") -> str:
    """Convert an address into an Amap longitude,latitude coordinate."""
    params = {"key": amap_key, "address": address, "output": "json"}
    if city:
        params["city"] = city

    response = _get_response(AMAP_GEOCODE_URL, params)
    result = response.json()
    if result.get("status") != "1":
        raise RuntimeError(f"高德地址解析失败：{result.get('info', '未知错误')}")

    geocodes = result.get("geocodes", [])
    if (
        not isinstance(geocodes, list)
        or not geocodes
        or not isinstance(geocodes[0], dict)
        or not geocodes[0].get("location")
    ):
        raise RuntimeError(f"高德地址解析失败：未找到地址“{address}”")
    location = geocodes[0]["location"]
    if not isinstance(location, str) or not re.fullmatch(
        r"-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?", location
    ):
        raise RuntimeError("高德地址解析失败：返回的坐标格式无效")
    return location

def get_route_duration(
    origin: str,
    destination: str,
    waypoints: str,
    amap_key: str,
) -> tuple[int, int]:
    """Query Amap and return estimated travel time in seconds and distance in meters."""
    params = {
        "key": amap_key,
        "origin": origin,
        "destination": destination,
        "strategy": "0",
        "extensions": "base",
    }
    if waypoints:
        params["waypoints"] = waypoints

    response = _get_response(AMAP_DIRECTION_URL, params)
    result = response.json()
    if result.get("status") != "1":
        raise RuntimeError(f"高德路线查询失败：{result.get('info', '未知错误')}")

    paths = result.get("route", {}).get("paths", [])
    if not paths:
        raise RuntimeError("高德路线查询失败：未找到路线")

    try:
        duration = int(paths[0]["duration"])
        distance = int(paths[0]["distance"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("高德路线响应缺少有效的耗时或距离") from exc
    if duration <= 0:
        raise RuntimeError("高德路线查询失败：路线耗时无效")
    return duration, distance