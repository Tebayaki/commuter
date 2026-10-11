#!/usr/bin/env python3

import logging
import os
import re
import signal
from dataclasses import dataclass, replace
from datetime import time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from .serverchan import push_message
from .amap import geocode_address, get_route_duration

logger = logging.getLogger(__name__)


def parse_workdays(value: str) -> str:
    """Convert comma-separated weekdays (1=Monday through 7=Sunday) for APScheduler."""
    WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    if not re.fullmatch(r"[1-7](?:\s*,\s*[1-7])*", value):
        raise ValueError("WORKDAYS 必须是逗号分隔的数字 1-7（1=周一，7=周日）")

    weekdays = dict.fromkeys(int(day.strip()) for day in value.split(","))
    return ",".join(WEEKDAY_NAMES[day - 1] for day in weekdays)


def weekdays_to_readable_text(value: str) -> str:
    """Convert comma-separated APScheduler weekdays to human readable text."""
    WEEKDAYS = {"mon": "一", "tue": "二", "wed": "三", "thu": "四", "fri": "五", "sat": "六", "sun": "日"}
    selected = value.split(",")
    if (set(selected) == set(WEEKDAYS)):
        return "每天"
    return "每周" + "、".join(WEEKDAYS[day] for day in WEEKDAYS if day in selected)


def _handle_sigterm(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


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
    workdays: str
    timezone: str

    @classmethod
    def from_environment(cls) -> "Settings":
        required_variables = (
            "AMAP_KEY",
            "SERVERCHAN_KEY",
            "HOME_POINT",
            "WORK_POINT",
            "HOME_TO_WORK_WAYPOINTS_A",
            "HOME_TO_WORK_WAYPOINTS_B",
            "WORK_TO_HOME_WAYPOINTS_A",
            "WORK_TO_HOME_WAYPOINTS_B",
        )
        values = {name: os.environ.get(name, "").strip() for name in required_variables}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                f"请配置必需的环境变量：{', '.join(missing)}"
            )

        work_time = os.environ.get("WORK_TIME", "09:00")
        home_time = os.environ.get("HOME_TIME", "17:00")
        workdays = os.environ.get("WORKDAYS", "1,2,3,4,5")
        timezone = os.environ.get("TIMEZONE", "Asia/Shanghai")

        time_pattern = r"(?:[01]\d|2[0-3]):[0-5]\d"
        if not re.fullmatch(time_pattern, work_time) or not re.fullmatch(time_pattern, home_time):
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式")
        try:
            work_time = time.fromisoformat(work_time)
            home_time = time.fromisoformat(home_time)
        except ValueError as exc:
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式") from exc
        workdays = parse_workdays(workdays)

        return cls(
            amap_key=values["AMAP_KEY"],
            serverchan_key=values["SERVERCHAN_KEY"],
            home_point=values["HOME_POINT"],
            work_point=values["WORK_POINT"],
            home_to_work_waypoints_a=values["HOME_TO_WORK_WAYPOINTS_A"],
            home_to_work_waypoints_b=values["HOME_TO_WORK_WAYPOINTS_B"],
            work_to_home_waypoints_a=values["WORK_TO_HOME_WAYPOINTS_A"],
            work_to_home_waypoints_b=values["WORK_TO_HOME_WAYPOINTS_B"],
            work_time=work_time,
            home_time=home_time,
            workdays=workdays,
            timezone=timezone,
        )


def resolve_location(value: str, amap_key: str) -> str:
    """Return coordinates unchanged or geocode an address optionally prefixed by city@."""
    value = value.strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?", value):
        return value

    if "@" in value:
        city, address = value.split("@", maxsplit=1)
    else:
        city, address = "", value
    if not address.strip():
        raise ValueError("地址不能为空，格式应为 city@address 或 address")
    return geocode_address(address.strip(), amap_key, city.strip())


def resolve_waypoints(value: str, amap_key: str) -> str:
    """Resolve a semicolon-separated list of coordinates and/or addresses."""
    return ";".join(
        resolve_location(location, amap_key)
        for location in value.split(";")
    )


def resolve_locations(settings: Settings) -> Settings:
    """Resolve endpoints and route waypoints before starting evaluations."""
    return replace(
        settings,
        home_point=resolve_location(settings.home_point, settings.amap_key),
        work_point=resolve_location(settings.work_point, settings.amap_key),
        home_to_work_waypoints_a=resolve_waypoints(
            settings.home_to_work_waypoints_a, settings.amap_key
        ),
        home_to_work_waypoints_b=resolve_waypoints(
            settings.home_to_work_waypoints_b, settings.amap_key
        ),
        work_to_home_waypoints_a=resolve_waypoints(
            settings.work_to_home_waypoints_a, settings.amap_key
        ),
        work_to_home_waypoints_b=resolve_waypoints(
            settings.work_to_home_waypoints_b, settings.amap_key
        ),
    )

def evaluate_routes(
    commute_name: str,
    departure: str,
    destination: str,
    waypoints_a: str,
    waypoints_b: str,
    settings: Settings,
    *,
    notify_when_a_is_faster: bool = False,
) -> None:
    """Compare routes A and B and notify according to the configured policy."""
    duration_a, distance_a = get_route_duration(
        departure, destination, waypoints_a, settings.amap_key
    )
    duration_b, distance_b = get_route_duration(
        departure, destination, waypoints_b, settings.amap_key
    )

    if duration_b >= duration_a and not notify_when_a_is_faster:
        logger.info(
            "%s：B路线未更快（A %d 分钟，B %d 分钟），不推送",
            commute_name,
            duration_a // 60,
            duration_b // 60,
        )
        return

    if duration_b < duration_a:
        recommended = "B 路线"
        faster_by = (duration_a - duration_b) // 60
    else:
        recommended = "A 路线"
        faster_by = (duration_b - duration_a) // 60

    content = (
        f"## 建议：{commute_name}走 {recommended}，预计快 {faster_by} 分钟\n\n"
        "| 路线 | 耗时 | 距离 |\n"
        "|------|------|------|\n"
        f"| A 路线 | {duration_a // 60} 分钟 | {distance_a / 1000:.1f} km |\n"
        f"| B 路线 | {duration_b // 60} 分钟 | {distance_b / 1000:.1f} km |\n"
    )
    push_message(
        f"通勤建议：{commute_name}走 {recommended}",
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
            day_of_week=settings.workdays,
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
            day_of_week=settings.workdays,
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
    settings = resolve_locations(Settings.from_environment())
    scheduler = create_scheduler(settings)
    logger.info(
        "通勤评估任务已创建，%s 的 %s 和 %s 执行（时区：%s）",
        weekdays_to_readable_text(settings.workdays),
        settings.work_time.strftime("%H:%M"),
        settings.home_time.strftime("%H:%M"),
        settings.timezone,
    )
    previous_sigterm_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C 或 SIGTERM，正在关闭调度器并等待正在运行的任务")
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if scheduler.running:
            scheduler.shutdown(wait=True)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
