import unittest
from datetime import time
from unittest.mock import MagicMock, call, patch

from commuter.commuter import (
    Settings,
    create_scheduler,
    evaluate_routes,
    parse_work_days,
)


class CommuterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            amap_key="amap-test-key",
            serverchan_key="serverchan-test-key",
            home_point="home",
            work_point="work",
            home_to_work_waypoints_a="morning-a",
            home_to_work_waypoints_b="morning-b",
            work_to_home_waypoints_a="evening-a",
            work_to_home_waypoints_b="evening-b",
            work_time=time(7, 45),
            home_time=time(18, 15),
            work_day="1,2,3,4,5",
            timezone="Asia/Shanghai",
        )

    @patch("commuter.commuter.push_message")
    @patch("commuter.commuter.get_route_duration")
    def test_pushes_when_route_b_is_faster(
        self, get_route_duration: MagicMock, push_message: MagicMock
    ) -> None:
        get_route_duration.side_effect = [(2400, 12000), (1800, 10000)]

        evaluate_routes(
            "上班", "home", "work", "morning-a", "morning-b", self.settings
        )

        push_message.assert_called_once()
        args = push_message.call_args.args
        self.assertIn("B 路线", args[0])
        self.assertIn("快 10 分钟", args[1])
        self.assertEqual(
            get_route_duration.call_args_list,
            [
                call("home", "work", "morning-a", "amap-test-key"),
                call("home", "work", "morning-b", "amap-test-key"),
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
            ("home", "work", "morning-a", "morning-b"),
        )
        self.assertEqual(
            jobs["evening-commute"].args[1:5],
            ("work", "home", "evening-a", "evening-b"),
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
            "WORK_DAY": "1,2,3,4,5",
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
        self.assertEqual(settings.work_day, "1,2,3,4,5")

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
        self.assertEqual(settings.work_day, "1,2,3,4,5")
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
            "WORK_DAY": "1,2,3,4,5",
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
            "WORK_DAY": "mon-fri",
        },
        clear=True,
    )
    def test_settings_reject_invalid_work_day(self) -> None:
        with self.assertRaisesRegex(ValueError, "WORK_DAY"):
            Settings.from_environment()

    def test_work_day_numbers_map_monday_through_sunday(self) -> None:
        self.assertEqual(parse_work_days("1,2,3,4,5"), "mon,tue,wed,thu,fri")
        self.assertEqual(parse_work_days("7,1"), "sun,mon")

    def test_work_day_rejects_values_outside_one_through_seven(self) -> None:
        for invalid_days in ("0", "8", "1,,2", "1, mon", "1-5", ""):
            with self.subTest(invalid_days=invalid_days):
                with self.assertRaisesRegex(ValueError, "WORK_DAY"):
                    parse_work_days(invalid_days)

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


if __name__ == "__main__":
    unittest.main()
