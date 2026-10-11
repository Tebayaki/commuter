import os
import signal
import tempfile
import unittest
from dataclasses import replace
from datetime import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from commuter.amap import geocode_address
from commuter.commuter import (
    Route,
    Settings,
    create_scheduler,
    evaluate_routes,
    load_config,
    parse_workdays,
    resolve_location,
    resolve_locations,
)
from commuter.once import run_once


CONFIG = """\
amap_key: amap-test-key
serverchan_key: serverchan-test-key
work_time: "07:45"
home_time: "18:15"
workdays: "1,2,3,4,5"
timezone: Asia/Shanghai
home_point:
  coordinate: "116.397463,39.909187"
work_point:
  city: 北京
  address: 公司地址
home_to_work_routes:
  - name: 路线A
    waypoints:
      - coordinate: "116.410000,39.910000"
  - name: 路线B
    waypoints:
      - city: 北京
        address: 途经点B
work_to_home_routes:
  - name: 回家路线A
    waypoints: []
  - name: 回家路线B
    waypoints:
      - city: 北京
        address: 下班途经点
  - name: 回家路线C
    waypoints: []
push_when_first_route_win: false
"""


class CommuterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "config.yaml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        config = load_config(self.config_path)
        self.settings = Settings(
            amap_key=config["amap_key"],
            serverchan_key=config["serverchan_key"],
            home_point=config["home_point"],
            work_point=config["work_point"],
            home_to_work_routes=config["home_to_work_routes"],
            work_to_home_routes=config["work_to_home_routes"],
            push_when_first_route_win=config["push_when_first_route_win"],
            work_time=time.fromisoformat(config["work_time"]),
            home_time=time.fromisoformat(config["home_time"]),
            workdays=parse_workdays(config["workdays"]),
            timezone=config["timezone"],
        )

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_pushes_named_fastest_non_first_route(
        self, get_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_duration.side_effect = [(2400, 12000), (1800, 10000)]

        evaluate_routes(
            "上班",
            self.settings.home_point,
            self.settings.work_point,
            self.settings.home_to_work_routes,
            self.settings,
        )

        push_message.assert_called_once()
        self.assertIn("路线B", push_message.call_args.args[0])
        self.assertIn("路线B", push_message.call_args.args[1])
        self.assertIn("路线A", push_message.call_args.args[1])
        self.assertEqual(get_duration.call_count, 2)

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_does_not_notify_when_first_route_wins_by_default(
        self, get_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_duration.side_effect = [(1800, 10000), (2400, 12000)]

        evaluate_routes(
            "上班",
            self.settings.home_point,
            self.settings.work_point,
            self.settings.home_to_work_routes,
            self.settings,
        )

        push_message.assert_not_called()

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_notifies_when_first_route_wins_if_enabled(
        self, get_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_duration.side_effect = [(1800, 10000), (2400, 12000)]
        settings = replace(self.settings, push_when_first_route_win=True)

        evaluate_routes(
            "上班",
            settings.home_point,
            settings.work_point,
            settings.home_to_work_routes,
            settings,
        )

        push_message.assert_called_once()
        self.assertIn("路线A", push_message.call_args.args[0])

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_one_shot_always_notifies_and_evaluates_all_configured_routes(
        self, get_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_duration.side_effect = [
            (1800, 10000),
            (2400, 12000),
            (3000, 15000),
            (2700, 13000),
            (2100, 11000),
        ]

        with patch("commuter.once.resolve_locations", return_value=self.settings):
            run_once(self.settings)

        self.assertEqual(push_message.call_count, 2)
        self.assertIn("路线A", push_message.call_args_list[0].args[0])
        self.assertIn("回家路线C", push_message.call_args_list[1].args[0])
        self.assertEqual(get_duration.call_count, 5)

    def test_scheduler_has_two_jobs_with_configured_route_lists(self) -> None:
        scheduler = create_scheduler(self.settings)
        jobs = {job.id: job for job in scheduler.get_jobs()}

        self.assertEqual(set(jobs), {"morning-commute", "evening-commute"})
        morning = jobs["morning-commute"]
        evening = jobs["evening-commute"]
        self.assertEqual((morning.args[0], morning.args[3]), ("上班", self.settings.home_to_work_routes))
        self.assertEqual((evening.args[0], evening.args[3]), ("下班", self.settings.work_to_home_routes))
        self.assertEqual(morning.args[4], self.settings)
        self.assertEqual(evening.args[4], self.settings)

    def test_loads_yaml_locations_routes_and_push_policy(self) -> None:
        config = load_config(self.config_path)

        self.assertEqual(config["home_point"], "116.397463,39.909187")
        self.assertEqual(config["work_point"], "北京@公司地址")
        self.assertEqual(
            config["home_to_work_routes"],
            (
                Route("路线A", ("116.410000,39.910000",)),
                Route("路线B", ("北京@途经点B",)),
            ),
        )
        self.assertEqual(len(config["work_to_home_routes"]), 3)
        self.assertFalse(config["push_when_first_route_win"])

    def test_rejects_malformed_yaml_config_values(self) -> None:
        invalid_configs = (
            CONFIG.replace(
                "push_when_first_route_win: false",
                'push_when_first_route_win: "false"',
            ),
            CONFIG.replace("name: 路线A", "name: ''"),
            "home_point: 116,39\nwork_point: 117,40\nhome_to_work_routes: []\n"
            "work_to_home_routes:\n  - name: 回家\n",
        )
        for contents in invalid_configs:
            with self.subTest(contents=contents):
                self.config_path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(self.config_path)

    @patch.dict(
        os.environ,
        {"AMAP_KEY": "configured-amap", "SERVERCHAN_KEY": "configured-push"},
        clear=True,
    )
    def test_settings_read_credentials_and_schedule_from_yaml(self) -> None:
        config_text = CONFIG.replace(
            "amap_key: amap-test-key", 'amap_key: "${AMAP_KEY}"'
        ).replace(
            "serverchan_key: serverchan-test-key",
            'serverchan_key: "${SERVERCHAN_KEY}"',
        )
        self.config_path.write_text(config_text, encoding="utf-8")
        settings = Settings.from_config(self.config_path)

        self.assertEqual((settings.amap_key, settings.serverchan_key), ("configured-amap", "configured-push"))
        self.assertEqual(settings.work_time, time(7, 45))
        self.assertEqual(settings.home_time, time(18, 15))
        self.assertEqual(settings.workdays, "mon,tue,wed,thu,fri")
        self.assertEqual(settings.timezone, "Asia/Shanghai")

    def test_rejects_invalid_schedule_time(self) -> None:
        self.config_path.write_text(CONFIG.replace('"07:45"', '"7:45"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            Settings.from_config(self.config_path)

    def test_fails_clearly_when_config_references_unset_variable(self) -> None:
        self.config_path.write_text(
            CONFIG.replace("amap-test-key", "${MISSING_AMAP_KEY}"),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MISSING_AMAP_KEY"):
                load_config(self.config_path)

    def test_workdays_numbers_map_to_weekday_names(self) -> None:
        self.assertEqual(parse_workdays("1,2,3,4,5"), "mon,tue,wed,thu,fri")
        self.assertEqual(parse_workdays("7,1"), "sun,mon")
        with self.assertRaisesRegex(ValueError, "WORKDAYS"):
            parse_workdays("0")

    @patch("commuter.amap.requests.get")
    def test_geocode_address_returns_coordinate_and_passes_city(
        self, get_mock: MagicMock
    ) -> None:
        response = MagicMock()
        response.json.return_value = {
            "status": "1",
            "geocodes": [{"location": "116.480881,39.989410"}],
        }
        get_mock.return_value = response

        location = geocode_address("地址", "amap-test-key", "北京")

        self.assertEqual(location, "116.480881,39.989410")
        self.assertEqual(get_mock.call_args.kwargs["params"]["city"], "北京")
        response.raise_for_status.assert_called_once_with()

    @patch("commuter.commuter.geocode_address")
    def test_resolve_locations_geocodes_yaml_addresses_and_waypoints(
        self, geocode: MagicMock
    ) -> None:
        geocode.side_effect = ["work-coordinate", "morning-waypoint", "evening-waypoint"]
        resolved = resolve_locations(self.settings)

        self.assertEqual(resolved.home_point, "116.397463,39.909187")
        self.assertEqual(resolved.work_point, "work-coordinate")
        self.assertEqual(
            resolved.home_to_work_routes[1].waypoints, ("morning-waypoint",)
        )
        self.assertEqual(
            resolved.work_to_home_routes[1].waypoints,
            ("evening-waypoint",),
        )
        self.assertEqual(
            geocode.call_args_list,
            [
                call("公司地址", "amap-test-key", "北京"),
                call("途经点B", "amap-test-key", "北京"),
                call("下班途经点", "amap-test-key", "北京"),
            ],
        )

    @patch("commuter.commuter.geocode_address")
    def test_resolve_location_supports_optional_city_prefix(
        self, geocode: MagicMock
    ) -> None:
        geocode.return_value = "116.480881,39.989410"
        self.assertEqual(resolve_location("北京@地址", "key"), "116.480881,39.989410")
        self.assertEqual(resolve_location("地址", "key"), "116.480881,39.989410")
        self.assertEqual(
            geocode.call_args_list,
            [call("地址", "key", "北京"), call("地址", "key", "")],
        )

    @patch("commuter.commuter.Settings.from_config")
    @patch("commuter.commuter.load_dotenv")
    @patch("commuter.commuter.logging.basicConfig")
    @patch("commuter.commuter.create_scheduler")
    def test_ctrl_c_shuts_down_scheduler_cleanly(
        self,
        create_scheduler_mock: MagicMock,
        _basic_config_mock: MagicMock,
        _load_dotenv_mock: MagicMock,
        from_config_mock: MagicMock,
    ) -> None:
        scheduler = MagicMock()
        scheduler.start.side_effect = KeyboardInterrupt
        create_scheduler_mock.return_value = scheduler
        from_config_mock.return_value = self.settings

        from commuter.commuter import main

        with patch("commuter.commuter.resolve_locations", return_value=self.settings):
            main()

        scheduler.shutdown.assert_called_once_with(wait=True)


if __name__ == "__main__":
    unittest.main()
