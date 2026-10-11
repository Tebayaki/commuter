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
        settings.home_to_work_routes,
        settings,
        notify_when_first_route_wins=True,
    )
    evaluate_routes(
        "下班",
        settings.work_point,
        settings.home_point,
        settings.work_to_home_routes,
        settings,
        notify_when_first_route_wins=True,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    run_once(Settings.from_config())
