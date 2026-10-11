import logging

from dotenv import load_dotenv

from .commuter import Settings, evaluate_routes, resolve_locations

logger = logging.getLogger(__name__)


def run_once(settings: Settings) -> None:
    """Compare both commute directions once and always notify the faster route."""
    settings = resolve_locations(settings)
    evaluate_routes(
        "上班",
        settings.home_point,
        settings.work_point,
        settings.home_to_work_waypoints_a,
        settings.home_to_work_waypoints_b,
        settings,
        notify_when_a_is_faster=True,
    )
    evaluate_routes(
        "下班",
        settings.work_point,
        settings.home_point,
        settings.work_to_home_waypoints_a,
        settings.work_to_home_waypoints_b,
        settings,
        notify_when_a_is_faster=True,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    run_once(Settings.from_environment())
