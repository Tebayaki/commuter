#!/usr/bin/env python3

import logging
import os
import re
import signal
from dataclasses import dataclass, replace
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from .amap import geocode_address, get_route_duration
from .serverchan import push_message

logger = logging.getLogger(__name__)
ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_workdays(value: str) -> str:
    """Convert comma-separated weekdays (1=Monday through 7=Sunday) for APScheduler."""
    weekday_names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    if not re.fullmatch(r"[1-7](?:\s*,\s*[1-7])*", value):
        raise ValueError("WORKDAYS 必须是逗号分隔的数字 1-7（1=周一，7=周日）")

    weekdays = dict.fromkeys(int(day.strip()) for day in value.split(","))
    return ",".join(weekday_names[day - 1] for day in weekdays)


def weekdays_to_readable_text(value: str) -> str:
    """Convert comma-separated APScheduler weekdays to human readable text."""
    WEEKDAYS = {"mon": "一", "tue": "二", "wed": "三", "thu": "四", "fri": "五", "sat": "六", "sun": "日"}
    selected = value.split(",")
    if (set(selected) == set(WEEKDAYS)):
        return "每天"
    return "每周" + "、".join(WEEKDAYS[day] for day in WEEKDAYS if day in selected)


@dataclass(frozen=True)
class Route:
    name: str
    waypoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    amap_key: str
    serverchan_key: str
    home_point: str
    work_point: str
    home_to_work_routes: tuple[Route, ...]
    work_to_home_routes: tuple[Route, ...]
    push_when_first_route_win: bool
    work_time: time
    home_time: time
    workdays: str
    timezone: str

    @classmethod
    def from_config(cls, config_path: str | Path = "config.yaml") -> "Settings":
        config = load_config(config_path)
        work_time_text = config["work_time"]
        home_time_text = config["home_time"]
        time_pattern = r"(?:[01]\d|2[0-3]):[0-5]\d"
        if not re.fullmatch(time_pattern, work_time_text) or not re.fullmatch(
            time_pattern, home_time_text
        ):
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式")
        try:
            work_time = time.fromisoformat(work_time_text)
            home_time = time.fromisoformat(home_time_text)
        except ValueError as exc:
            raise ValueError("WORK_TIME 和 HOME_TIME 必须使用 HH:MM 格式") from exc

        amap_key = config["amap_key"].strip()
        serverchan_key = config["serverchan_key"].strip()
        missing = [
            name
            for name, value in (
                ("amap_key", amap_key),
                ("serverchan_key", serverchan_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"YAML 配置必须提供非空的 {', '.join(missing)}")

        return cls(
            amap_key=amap_key,
            serverchan_key=serverchan_key,
            home_point=config["home_point"],
            work_point=config["work_point"],
            home_to_work_routes=config["home_to_work_routes"],
            work_to_home_routes=config["work_to_home_routes"],
            push_when_first_route_win=config["push_when_first_route_win"],
            work_time=work_time,
            home_time=home_time,
            workdays=parse_workdays(config["workdays"]),
            timezone=config["timezone"],
        )


def _parse_location(value: Any, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是坐标/地址字符串或位置对象")

    coordinate = value.get("coordinate")
    city = value.get("city")
    address = value.get("address")
    if coordinate is not None:
        if not isinstance(coordinate, str) or not coordinate.strip():
            raise ValueError(f"{field_name}.coordinate 必须是非空字符串")
        if city is not None or address is not None:
            raise ValueError(f"{field_name} 不能同时配置 coordinate 和 address")
        return coordinate.strip()

    if not isinstance(address, str) or not address.strip():
        raise ValueError(f"{field_name}.address 必须是非空字符串")
    if city is not None and (not isinstance(city, str) or not city.strip()):
        raise ValueError(f"{field_name}.city 必须是非空字符串")
    return f"{city.strip()}@{address.strip()}" if city else address.strip()


def _parse_routes(value: Any, field_name: str) -> tuple[Route, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} 必须是至少包含一条路线的列表")

    routes = []
    for index, item in enumerate(value):
        route_field = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{route_field} 必须是对象")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{route_field}.name 必须是非空字符串")
        waypoints = item.get("waypoints", [])
        if not isinstance(waypoints, list):
            raise ValueError(f"{route_field}.waypoints 必须是列表")
        routes.append(
            Route(
                name=name.strip(),
                waypoints=tuple(
                    _parse_location(point, f"{route_field}.waypoints[{point_index}]")
                    for point_index, point in enumerate(waypoints)
                ),
            )
        )
    return tuple(routes)


def _expand_environment_variables(value: Any) -> Any:
    if isinstance(value, str):
        def replace_variable(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ValueError(
                    f"YAML 配置引用了未设置的环境变量：{name}"
                )
            return os.environ[name]

        return ENVIRONMENT_VARIABLE_PATTERN.sub(replace_variable, value)
    if isinstance(value, list):
        return [_expand_environment_variables(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _expand_environment_variables(item)
            for key, item in value.items()
        }
    return value


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load YAML settings and expand environment variable references."""
    path = Path(config_path)
    try:
        with path.open(encoding="utf-8") as config_file:
            config = _expand_environment_variables(yaml.safe_load(config_file))
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 配置文件格式错误：{path}") from exc
    except OSError as exc:
        raise ValueError(f"无法读取 YAML 配置文件：{path}") from exc

    if not isinstance(config, dict):
        raise ValueError("YAML 配置文件顶层必须是对象")
    amap_key = config.get("amap_key")
    serverchan_key = config.get("serverchan_key")
    work_time = config.get("work_time", "09:00")
    home_time = config.get("home_time", "17:00")
    workdays = config.get("workdays", "1,2,3,4,5")
    timezone = config.get("timezone", "Asia/Shanghai")
    for name, value in (
        ("amap_key", amap_key),
        ("serverchan_key", serverchan_key),
        ("work_time", work_time),
        ("home_time", home_time),
        ("workdays", workdays),
        ("timezone", timezone),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} 必须是非空字符串")

    notify = config.get("push_when_first_route_win", False)
    if not isinstance(notify, bool):
        raise ValueError("push_when_first_route_win 必须是 true 或 false")
    return {
        "amap_key": amap_key,
        "serverchan_key": serverchan_key,
        "home_point": _parse_location(config.get("home_point"), "home_point"),
        "work_point": _parse_location(config.get("work_point"), "work_point"),
        "home_to_work_routes": _parse_routes(
            config.get("home_to_work_routes"), "home_to_work_routes"
        ),
        "work_to_home_routes": _parse_routes(
            config.get("work_to_home_routes"), "work_to_home_routes"
        ),
        "push_when_first_route_win": notify,
        "work_time": work_time.strip(),
        "home_time": home_time.strip(),
        "workdays": workdays.strip(),
        "timezone": timezone.strip(),
    }


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


def resolve_locations(settings: Settings) -> Settings:
    """Resolve endpoints and all route waypoints before starting evaluations."""
    return replace(
        settings,
        home_point=resolve_location(settings.home_point, settings.amap_key),
        work_point=resolve_location(settings.work_point, settings.amap_key),
        home_to_work_routes=_resolve_routes(
            settings.home_to_work_routes, settings.amap_key
        ),
        work_to_home_routes=_resolve_routes(
            settings.work_to_home_routes, settings.amap_key
        ),
    )


def _resolve_routes(routes: tuple[Route, ...], amap_key: str) -> tuple[Route, ...]:
    return tuple(
        replace(
            route,
            waypoints=tuple(
                resolve_location(point, amap_key) for point in route.waypoints
            ),
        )
        for route in routes
    )


def evaluate_routes(
    commute_name: str,
    departure: str,
    destination: str,
    routes: tuple[Route, ...],
    settings: Settings,
    *,
    notify_when_first_route_wins: bool | None = None,
) -> None:
    """Query every configured route and notify for a non-first winner or when enabled."""
    results = [
        (
            route,
            *get_route_duration(
                departure,
                destination,
                ";".join(route.waypoints),
                settings.amap_key,
            ),
        )
        for route in routes
    ]
    winner_index = min(range(len(results)), key=lambda index: results[index][1])
    should_notify_first = (
        settings.push_when_first_route_win
        if notify_when_first_route_wins is None
        else notify_when_first_route_wins
    )
    if winner_index == 0 and not should_notify_first:
        logger.info(
            "%s：第一条路线“%s”最快（%d 分钟），按配置不推送",
            commute_name,
            results[0][0].name,
            results[0][1] // 60,
        )
        return

    winner = results[winner_index]
    alternative_durations = [
        result[1] for index, result in enumerate(results) if index != winner_index
    ]
    faster_by = (
        min(alternative_durations) - winner[1] if alternative_durations else 0
    )
    content = (
        f"## 建议：{commute_name}走 {winner[0].name}，预计快 {faster_by // 60} 分钟\n\n"
        "| 路线 | 耗时 | 距离 |\n"
        "|------|------|------|\n"
        + "".join(
            f"| {route.name} | {duration // 60} 分钟 | {distance / 1000:.1f} km |\n"
            for route, duration, distance in results
        )
    )
    push_message(
        f"通勤建议：{commute_name}走 {winner[0].name}",
        content,
        settings.serverchan_key,
    )
    logger.info("%s", content)


def _handle_sigterm(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


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
            settings.home_to_work_routes,
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
            settings.work_to_home_routes,
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
    settings = resolve_locations(Settings.from_config())
    scheduler = create_scheduler(settings)
    previous_sigterm_handler = signal.signal(signal.SIGTERM, _handle_sigterm)

    logger.info(
        "通勤评估任务已创建，每周 %s 的 %s 和 %s 执行（时区：%s）",
        weekdays_to_readable_text(settings.workdays),
        settings.work_time.strftime("%H:%M"),
        settings.home_time.strftime("%H:%M"),
        settings.timezone,
    )
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在等待运行中的任务完成并关闭调度器")
        scheduler.shutdown(wait=True)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
