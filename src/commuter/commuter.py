#!/usr/bin/env python3

import logging
import os
import re
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

AMAP_URL = "https://restapi.amap.com/v3/direction/driving"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    amap_key: str
    serverchan_key: str
    home_point: str
    work_point: str
    home_to_work_waypoints_a: str
    home_to_work_waypoints_b: str
    work_to_home_waypoints_a: str
    work_to_home_waypoints_b: str
    work_time: time
    home_time: time
    timezone: str

    @classmethod
    def from_environment(cls) -> "Settings":
        required_variables = (
            "AMAP_KEY",
            "SERVERCHAN_KEY",
            "HOME_POINT",
            "WORK_POINT",
            "WORK_TIME",
            "HOME_TIME",
        )
        values = {name: os.environ.get(name, "").strip() for name in required_variables}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                f"请配置必需的环境变量：{', '.join(missing)}"
            )

        time_pattern = r"(?:[01]\d|2[0-3]):[0-5]\d"
        if not re.fullmatch(time_pattern, values["WORK_TIME"]) or not re.fullmatch(
            time_pattern, values["HOME_TIME"]
        ):
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式")
        try:
            work_time = time.fromisoformat(values["WORK_TIME"])
            home_time = time.fromisoformat(values["HOME_TIME"])
        except ValueError as exc:
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式") from exc

        return cls(
            amap_key=values["AMAP_KEY"],
            serverchan_key=values["SERVERCHAN_KEY"],
            home_point=values["HOME_POINT"],
            work_point=values["WORK_POINT"],
            home_to_work_waypoints_a=os.environ.get(
                "HOME_TO_WORK_WAYPOINTS_A", ""
            ).strip(),
            home_to_work_waypoints_b=os.environ.get(
                "HOME_TO_WORK_WAYPOINTS_B", ""
            ).strip(),
            work_to_home_waypoints_a=os.environ.get(
                "WORK_TO_HOME_WAYPOINTS_A", ""
            ).strip(),
            work_to_home_waypoints_b=os.environ.get(
                "WORK_TO_HOME_WAYPOINTS_B", ""
            ).strip(),
            work_time=work_time,
            home_time=home_time,
            timezone=os.environ.get("TIMEZONE", "Asia/Shanghai"),
        )


def get_route_duration(
    departure: str,
    destination: str,
    waypoints: str,
    amap_key: str,
) -> tuple[int, int]:
    """Query Amap and return estimated travel time in seconds and distance in meters."""
    params = {
        "key": amap_key,
        "origin": departure,
        "destination": destination,
        "strategy": "0",
        "extensions": "base",
    }
    if waypoints:
        params["waypoints"] = waypoints

    response = requests.get(AMAP_URL, params=params, timeout=10)
    response.raise_for_status()
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


def push_message(title: str, content: str, serverchan_key: str) -> None:
    """Push a message through Server酱."""
    match = re.match(r"sctp(\d+)t", serverchan_key)
    uid = match.group(1) if match else serverchan_key[:3]
    api_url = f"https://{uid}.push.ft07.com/send/{serverchan_key}.send"
    response = requests.post(
        api_url,
        json={"title": title, "desp": content},
        timeout=10,
    )
    response.raise_for_status()


def evaluate_routes(
    commute_name: str,
    departure: str,
    destination: str,
    waypoints_a: str,
    waypoints_b: str,
    settings: Settings,
) -> None:
    """Compare routes A and B and notify only when route B is faster."""
    duration_a, distance_a = get_route_duration(
        departure, destination, waypoints_a, settings.amap_key
    )
    duration_b, distance_b = get_route_duration(
        departure, destination, waypoints_b, settings.amap_key
    )

    if duration_b >= duration_a:
        logger.info(
            "%s：B路线未更快（A %d 分钟，B %d 分钟），不推送",
            commute_name,
            duration_a // 60,
            duration_b // 60,
        )
        return

    faster_by = (duration_a - duration_b) // 60
    content = (
        f"## 建议：{commute_name}走 B 路线，预计快 {faster_by} 分钟\n\n"
        "| 路线 | 耗时 | 距离 |\n"
        "|------|------|------|\n"
        f"| A 路线 | {duration_a // 60} 分钟 | {distance_a / 1000:.1f} km |\n"
        f"| B 路线 | {duration_b // 60} 分钟 | {distance_b / 1000:.1f} km |\n"
    )
    push_message(
        f"通勤建议：{commute_name}走 B 路线",
        content,
        settings.serverchan_key,
    )
    logger.info("%s", content)


def create_scheduler(settings: Settings) -> BlockingScheduler:
    """Create the daily commute evaluation jobs using configured times."""
    scheduler_timezone = ZoneInfo(settings.timezone)
    scheduler = BlockingScheduler(timezone=scheduler_timezone)
    scheduler.add_job(
        evaluate_routes,
        trigger=CronTrigger(
            hour=settings.work_time.hour,
            minute=settings.work_time.minute,
            timezone=scheduler_timezone,
        ),
        args=[
            "上班",
            settings.home_point,
            settings.work_point,
            settings.home_to_work_waypoints_a,
            settings.home_to_work_waypoints_b,
            settings,
        ],
        id="morning-commute",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        evaluate_routes,
        trigger=CronTrigger(
            hour=settings.home_time.hour,
            minute=settings.home_time.minute,
            timezone=scheduler_timezone,
        ),
        args=[
            "下班",
            settings.work_point,
            settings.home_point,
            settings.work_to_home_waypoints_a,
            settings.work_to_home_waypoints_b,
            settings,
        ],
        id="evening-commute",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    settings = Settings.from_environment()
    logger.info(
        "通勤评估任务已启动，每天 %s 和 %s 执行（时区：%s）",
        settings.work_time.strftime("%H:%M"),
        settings.home_time.strftime("%H:%M"),
        settings.timezone,
    )
    scheduler = create_scheduler(settings)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt event received, shutting down scheduler...")
        scheduler.shutdown(wait=True)
