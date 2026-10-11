import signal
import unittest
from dataclasses import replace
from datetime import time
from unittest.mock import MagicMock, call, patch

from commuter.commuter import (
    Settings,
    create_scheduler,
    evaluate_routes,
    parse_workdays,
    resolve_location,
    resolve_locations,
    resolve_waypoints,
    weekdays_to_readable_text,
)
from commuter.amap import geocode_address
from commuter.once import run_once


class CommuterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            amap_key="amap-test-key",
            serverchan_key="serverchan-test-key",
            home_point="116.397463,39.909187",
            work_point="116.480881,39.989410",
            home_to_work_waypoints_a="116.410000,39.910000",
            home_to_work_waypoints_b="116.420000,39.920000",
            work_to_home_waypoints_a="116.430000,39.930000",
            work_to_home_waypoints_b="116.440000,39.940000",
            work_time=time(7, 45),
            home_time=time(18, 15),
            workdays="mon,tue,wed,thu,fri",
            timezone="Asia/Shanghai",
        )

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_pushes_when_route_b_is_faster(
        self, get_route_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_route_duration.side_effect = [(2400, 12000), (1800, 10000)]

        evaluate_routes(
            "上班",
            self.settings.home_point,
            self.settings.work_point,
            self.settings.home_to_work_waypoints_a,
            self.settings.home_to_work_waypoints_b,
            self.settings,
        )

        push_message.assert_called_once()
        args = push_message.call_args.args
        self.assertIn("B 路线", args[0])
        self.assertIn("快 10 分钟", args[1])
        self.assertEqual(
            get_route_duration.call_args_list,
            [
                call(
                    "116.397463,39.909187",
                    "116.480881,39.989410",
                    "116.410000,39.910000",
                    "amap-test-key",
                ),
                call(
                    "116.397463,39.909187",
                    "116.480881,39.989410",
                    "116.420000,39.920000",
                    "amap-test-key",
                ),
            ],
        )

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_does_not_push_when_route_b_is_not_faster(
        self, get_route_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_route_duration.side_effect = [(1800, 10000), (1800, 11000)]

        evaluate_routes(
            "下班", "work", "home", "evening-a", "evening-b", self.settings
        )

        push_message.assert_not_called()

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_one_shot_pushes_recommendation_for_a_and_b_winners(
        self, get_route_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_route_duration.side_effect = [
            (1800, 10000),
            (2400, 12000),
            (3000, 15000),
            (2100, 11000),
        ]

        run_once(self.settings)

        self.assertEqual(push_message.call_count, 2)
        self.assertIn("上班走 A 路线", push_message.call_args_list[0].args[0])
        self.assertIn("下班走 B 路线", push_message.call_args_list[1].args[0])
        self.assertIn("A 路线", push_message.call_args_list[0].args[1])
        self.assertIn("B 路线", push_message.call_args_list[1].args[1])
        self.assertEqual(get_route_duration.call_count, 4)

    def test_scheduler_has_morning_and_evening_jobs(self) -> None:
        scheduler = create_scheduler(self.settings)
        jobs = {job.id: job for job in scheduler.get_jobs()}

        self.assertEqual(set(jobs), {"morning-commute", "evening-commute"})
        morning_fields = {
            field.name: str(field) for field in jobs["morning-commute"].trigger.fields
        }
        evening_fields = {
            field.name: str(field) for field in jobs["evening-commute"].trigger.fields
        }
        self.assertEqual(
            (morning_fields["hour"], morning_fields["minute"]), ("7", "45")
        )
        self.assertEqual(
            (evening_fields["hour"], evening_fields["minute"]), ("18", "15")
        )
        self.assertEqual(morning_fields["day_of_week"], "mon,tue,wed,thu,fri")
        self.assertEqual(evening_fields["day_of_week"], "mon,tue,wed,thu,fri")
        self.assertEqual(
            jobs["morning-commute"].args[1:5],
            (
                "116.397463,39.909187",
                "116.480881,39.989410",
                "116.410000,39.910000",
                "116.420000,39.920000",
            ),
        )
        self.assertEqual(
            jobs["evening-commute"].args[1:5],
            (
                "116.480881,39.989410",
                "116.397463,39.909187",
                "116.430000,39.930000",
                "116.440000,39.940000",
            ),
        )

    @patch.dict(
        "os.environ",
        {
            "AMAP_KEY": "configured-amap-key",
            "SERVERCHAN_KEY": "configured-serverchan-key",
            "HOME_POINT": "configured-home",
            "WORK_POINT": "configured-work",
            "HOME_TO_WORK_WAYPOINTS_A": "configured-morning-a",
            "HOME_TO_WORK_WAYPOINTS_B": "configured-morning-b",
            "WORK_TO_HOME_WAYPOINTS_A": "configured-evening-a",
            "WORK_TO_HOME_WAYPOINTS_B": "configured-evening-b",
            "WORK_TIME": "06:35",
            "HOME_TIME": "19:20",
            "WORKDAYS": "1,2,3,4,5",
        },
        clear=True,
    )
    def test_settings_load_coordinates_and_times_from_environment(self) -> None:
        settings = Settings.from_environment()

        self.assertEqual(settings.home_point, "configured-home")
        self.assertEqual(settings.work_point, "configured-work")
        self.assertEqual(
            settings.home_to_work_waypoints_a, "configured-morning-a"
        )
        self.assertEqual(
            settings.home_to_work_waypoints_b, "configured-morning-b"
        )
        self.assertEqual(
            settings.work_to_home_waypoints_a, "configured-evening-a"
        )
        self.assertEqual(
            settings.work_to_home_waypoints_b, "configured-evening-b"
        )
        self.assertEqual(settings.work_time, time(6, 35))
        self.assertEqual(settings.home_time, time(19, 20))
        self.assertEqual(settings.workdays, "mon,tue,wed,thu,fri")

    @patch.dict(
        "os.environ",
        {
            "AMAP_KEY": "configured-amap-key",
            "SERVERCHAN_KEY": "configured-serverchan-key",
            "HOME_POINT": "configured-home",
            "WORK_POINT": "configured-work",
            "HOME_TO_WORK_WAYPOINTS_A": "configured-morning-a",
            "HOME_TO_WORK_WAYPOINTS_B": "configured-morning-b",
            "WORK_TO_HOME_WAYPOINTS_A": "configured-evening-a",
            "WORK_TO_HOME_WAYPOINTS_B": "configured-evening-b",
        },
        clear=True,
    )
    def test_settings_use_readme_defaults_for_optional_environment(
        self,
    ) -> None:
        settings = Settings.from_environment()

        self.assertEqual(settings.work_time, time(9, 0))
        self.assertEqual(settings.home_time, time(17, 0))
        self.assertEqual(settings.workdays, "mon,tue,wed,thu,fri")
        self.assertEqual(settings.timezone, "Asia/Shanghai")

    @patch.dict(
        "os.environ",
        {
            "AMAP_KEY": "configured-amap-key",
            "SERVERCHAN_KEY": "configured-serverchan-key",
            "HOME_POINT": "configured-home",
            "WORK_POINT": "configured-work",
            "HOME_TO_WORK_WAYPOINTS_A": "configured-morning-a",
            "HOME_TO_WORK_WAYPOINTS_B": "configured-morning-b",
            "WORK_TO_HOME_WAYPOINTS_A": "configured-evening-a",
            "WORK_TO_HOME_WAYPOINTS_B": "configured-evening-b",
            "WORK_TIME": "6:35",
            "HOME_TIME": "19:20",
            "WORKDAYS": "1,2,3,4,5",
        },
        clear=True,
    )
    def test_settings_reject_invalid_schedule_time_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            Settings.from_environment()

    @patch.dict(
        "os.environ",
        {
            "AMAP_KEY": "configured-amap-key",
            "SERVERCHAN_KEY": "configured-serverchan-key",
            "HOME_POINT": "configured-home",
            "WORK_POINT": "configured-work",
            "HOME_TO_WORK_WAYPOINTS_A": "configured-morning-a",
            "HOME_TO_WORK_WAYPOINTS_B": "configured-morning-b",
            "WORK_TO_HOME_WAYPOINTS_A": "configured-evening-a",
            "WORK_TO_HOME_WAYPOINTS_B": "configured-evening-b",
            "WORK_TIME": "06:35",
            "HOME_TIME": "19:20",
            "WORKDAYS": "weekday",
        },
        clear=True,
    )
    def test_settings_reject_invalid_workdays(self) -> None:
        with self.assertRaisesRegex(ValueError, "WORKDAYS"):
            Settings.from_environment()

    @patch.dict(
        "os.environ",
        {
            "AMAP_KEY": "configured-amap-key",
            "SERVERCHAN_KEY": "configured-serverchan-key",
            "HOME_POINT": "北京@北京市朝阳区阜通东大街6号",
            "WORK_POINT": "北京市海淀区中关村大街1号",
            "HOME_TO_WORK_WAYPOINTS_A": "morning-a",
            "HOME_TO_WORK_WAYPOINTS_B": "morning-b",
            "WORK_TO_HOME_WAYPOINTS_A": "evening-a",
            "WORK_TO_HOME_WAYPOINTS_B": "evening-b",
        },
        clear=True,
    )
    def test_settings_accept_addresses_instead_of_coordinates(self) -> None:
        settings = Settings.from_environment()

        self.assertEqual(
            settings.home_point, "北京@北京市朝阳区阜通东大街6号"
        )
        self.assertEqual(settings.work_point, "北京市海淀区中关村大街1号")

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

        location = geocode_address(
            "北京市朝阳区阜通东大街6号", "amap-test-key", "北京"
        )

        self.assertEqual(location, "116.480881,39.989410")
        get_mock.assert_called_once_with(
            "https://restapi.amap.com/v3/geocode/geo",
            params={
                "key": "amap-test-key",
                "address": "北京市朝阳区阜通东大街6号",
                "output": "json",
                "city": "北京",
            },
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("commuter.amap.requests.get")
    def test_geocode_address_raises_when_no_match(self, get_mock: MagicMock) -> None:
        response = MagicMock()
        response.json.return_value = {"status": "1", "geocodes": []}
        get_mock.return_value = response

        with self.assertRaisesRegex(RuntimeError, "未找到地址"):
            geocode_address("未知地址", "amap-test-key")

    @patch("commuter.commuter.geocode_address")
    def test_resolve_location_handles_coordinates_and_city_address(
        self, geocode_mock: MagicMock
    ) -> None:
        geocode_mock.return_value = "116.480881,39.989410"

        coordinate = resolve_location("116.397463,39.909187", "amap-test-key")
        city_address = resolve_location(
            "北京@阜通东大街6号", "amap-test-key"
        )
        address_without_city = resolve_location("中关村大街1号", "amap-test-key")

        self.assertEqual(coordinate, "116.397463,39.909187")
        self.assertEqual(city_address, "116.480881,39.989410")
        self.assertEqual(address_without_city, "116.480881,39.989410")
        self.assertEqual(
            geocode_mock.call_args_list,
            [
                call("阜通东大街6号", "amap-test-key", "北京"),
                call("中关村大街1号", "amap-test-key", ""),
            ],
        )

    def test_resolve_location_rejects_city_without_address(self) -> None:
        with self.assertRaisesRegex(ValueError, "地址不能为空"):
            resolve_location("北京@", "amap-test-key")

    @patch("commuter.commuter.resolve_location")
    def test_resolve_waypoints_preserves_multiple_semicolon_separated_points(
        self, resolve_mock: MagicMock
    ) -> None:
        resolve_mock.side_effect = [
            "116.39,39.90",
            "116.40,39.91",
            "116.41,39.92",
        ]

        result = resolve_waypoints(
            "116.39,39.90;北京@阜通东大街6号;上海@人民广场",
            "amap-test-key",
        )

        self.assertEqual(result, "116.39,39.90;116.40,39.91;116.41,39.92")
        self.assertEqual(
            resolve_mock.call_args_list,
            [
                call("116.39,39.90", "amap-test-key"),
                call("北京@阜通东大街6号", "amap-test-key"),
                call("上海@人民广场", "amap-test-key"),
            ],
        )

    @patch("commuter.commuter.geocode_address")
    def test_resolve_locations_geocodes_address_locations_only(
        self, geocode_mock: MagicMock
    ) -> None:
        settings = replace(
            self.settings,
            home_point="家庭城市@家庭地址",
            work_point="公司城市@公司地址",
            home_to_work_waypoints_a="家庭城市@途经点甲",
            home_to_work_waypoints_b="116.1,39.1",
            work_to_home_waypoints_a="公司城市@途经点乙",
            work_to_home_waypoints_b="公司城市@途经点丙",
        )
        geocode_mock.side_effect = [
            "home-coordinate",
            "work-coordinate",
            "morning-waypoint",
            "evening-waypoint-a",
            "evening-waypoint-b",
        ]

        resolved = resolve_locations(settings)

        self.assertEqual(resolved.home_point, "home-coordinate")
        self.assertEqual(resolved.work_point, "work-coordinate")
        self.assertEqual(
            resolved.home_to_work_waypoints_a, "morning-waypoint"
        )
        self.assertEqual(resolved.home_to_work_waypoints_b, "116.1,39.1")
        self.assertEqual(
            resolved.work_to_home_waypoints_a, "evening-waypoint-a"
        )
        self.assertEqual(
            resolved.work_to_home_waypoints_b, "evening-waypoint-b"
        )
        self.assertEqual(
            geocode_mock.call_args_list,
            [
                call("家庭地址", "amap-test-key", "家庭城市"),
                call("公司地址", "amap-test-key", "公司城市"),
                call("途经点甲", "amap-test-key", "家庭城市"),
                call("途经点乙", "amap-test-key", "公司城市"),
                call("途经点丙", "amap-test-key", "公司城市"),
            ],
        )

    def test_workdays_numbers_map_monday_through_sunday(self) -> None:
        self.assertEqual(parse_workdays("1,2,3,4,5"), "mon,tue,wed,thu,fri")
        self.assertEqual(parse_workdays("7,1"), "sun,mon")

    def test_workdays_reject_values_outside_one_through_seven(self) -> None:
        for invalid_days in ("0", "8", "1,,2", "1, mon", "1-5", ""):
            with self.subTest(invalid_days=invalid_days):
                with self.assertRaisesRegex(ValueError, "WORKDAYS"):
                    parse_workdays(invalid_days)

    def test_weekdays_to_readable_text(self) -> None:
        self.assertEqual(
            weekdays_to_readable_text("mon,tue,wed,thu,fri"),
            "每周一、二、三、四、五",
        )
        self.assertEqual(
            weekdays_to_readable_text("mon,tue,wed,thu,fri,sat,sun"),
            "每天",
        )

    @patch("commuter.commuter.Settings.from_environment")
    @patch("commuter.commuter.load_dotenv")
    @patch("commuter.commuter.logging.basicConfig")
    @patch("commuter.commuter.create_scheduler")
    def test_ctrl_c_shuts_down_scheduler_cleanly(
        self,
        create_scheduler_mock: MagicMock,
        _basic_config_mock: MagicMock,
        _load_dotenv_mock: MagicMock,
        from_environment_mock: MagicMock,
    ) -> None:
        scheduler = MagicMock()
        scheduler.start.side_effect = KeyboardInterrupt
        create_scheduler_mock.return_value = scheduler
        from_environment_mock.return_value = self.settings

        from commuter.commuter import main

        main()

        scheduler.start.assert_called_once_with()
        scheduler.shutdown.assert_called_once_with(wait=True)

    @patch("commuter.commuter.Settings.from_environment")
    @patch("commuter.commuter.load_dotenv")
    @patch("commuter.commuter.logging.basicConfig")
    @patch("commuter.commuter.create_scheduler")
    def test_sigterm_shuts_down_scheduler_and_restores_handler(
        self,
        create_scheduler_mock: MagicMock,
        _basic_config_mock: MagicMock,
        _load_dotenv_mock: MagicMock,
        from_environment_mock: MagicMock,
    ) -> None:
        scheduler = MagicMock()
        create_scheduler_mock.return_value = scheduler
        from_environment_mock.return_value = self.settings
        handlers = {}

        def fake_signal(signum: int, handler: object) -> object:
            previous_handler = handlers.get(signum, signal.SIG_DFL)
            handlers[signum] = handler
            return previous_handler

        scheduler.start.side_effect = lambda: handlers[signal.SIGTERM](
            signal.SIGTERM, None
        )

        from commuter.commuter import main

        with patch("commuter.commuter.signal.signal", side_effect=fake_signal):
            main()

        scheduler.start.assert_called_once_with()
        scheduler.shutdown.assert_called_once_with(wait=True)
        self.assertIs(handlers[signal.SIGTERM], signal.SIG_DFL)


if __name__ == "__main__":
    unittest.main()
