import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import db
import export
import collector
import mock_data
import providers


CN = timezone(timedelta(hours=8))


class PipelineTests(unittest.TestCase):
    def test_provider_dispatch_defaults_to_sina(self):
        rows = [{"code": "A"}]
        with patch("providers.sina.fetch_board_snapshot", return_value=rows) as fetch:
            result = providers.fetch_sector_snapshot("industry", provider="sina")

        self.assertEqual(result, rows)
        fetch.assert_called_once_with("industry")

    def test_provider_dispatches_to_ths(self):
        rows = [{"code": "THS-A"}]
        with patch("providers.ths.fetch_board_snapshot", return_value=rows) as fetch:
            result = providers.fetch_sector_snapshot("industry", provider="ths")

        self.assertEqual(result, rows)
        fetch.assert_called_once_with("industry")

    def test_write_payload_uses_utf8(self):
        payload = {"title": "新浪板块净流入", "series": []}
        with tempfile.TemporaryDirectory() as td:
            out = export.write_payload(payload, Path(td) / "2026-08-29.json")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

    def test_export_prefers_larger_absolute_value_for_duplicate_board_names(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "flow.db"
            db.init(db_path)
            db.upsert(
                [
                    {"sector_type": "industry", "code": "I", "name": "测试", "main_net": 100_000_000},
                    {"sector_type": "concept", "code": "C", "name": "测试", "main_net": 500_000_000},
                ],
                trade_date="2026-08-29",
                ts="2026-08-29 09:31:00",
                session_min=0,
                db_path=db_path,
            )

            payload = export.build(
                trade_date="2026-08-29",
                db_path=db_path,
                config={"watchlist": ["测试"]},
            )

        self.assertEqual(payload["series"][0]["code"], "C")
        self.assertEqual(payload["series"][0]["data"][0], 5.0)

    def test_export_tracks_a_board_code_after_name_change(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "flow.db"
            db.init(db_path)
            db.upsert(
                [{"sector_type": "industry", "code": "R", "name": "旧名", "main_net": 100_000_000}],
                trade_date="2026-08-29",
                ts="2026-08-29 09:31:00",
                session_min=0,
                db_path=db_path,
            )
            db.upsert(
                [{"sector_type": "industry", "code": "R", "name": "新名", "main_net": 300_000_000}],
                trade_date="2026-08-29",
                ts="2026-08-29 09:32:00",
                session_min=1,
                db_path=db_path,
            )

            payload = export.build(
                trade_date="2026-08-29",
                db_path=db_path,
                config={"watchlist": ["旧名"]},
            )

        self.assertEqual(payload["series"][0]["code"], "R")
        self.assertEqual(payload["series"][0]["data"][:2], [1.0, 3.0])

    def test_export_leaves_future_points_empty_after_last_observation(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "flow.db"
            db.init(db_path)
            db.upsert(
                [{"sector_type": "industry", "code": "A", "name": "测试", "main_net": 100_000_000}],
                trade_date="2026-08-29",
                ts="2026-08-29 09:31:00",
                session_min=0,
                db_path=db_path,
            )
            db.upsert(
                [{"sector_type": "industry", "code": "A", "name": "测试", "main_net": 200_000_000}],
                trade_date="2026-08-29",
                ts="2026-08-29 09:32:00",
                session_min=1,
                db_path=db_path,
            )

            payload = export.build(
                trade_date="2026-08-29",
                db_path=db_path,
                config={"watchlist": ["测试"]},
            )

        self.assertEqual(payload["series"][0]["data"][:2], [1.0, 2.0])
        self.assertIsNone(payload["series"][0]["data"][2])
        self.assertIsNone(payload["series"][0]["data"][-1])

    def test_run_once_writes_sqlite_and_same_day_json(self):
        rows = [{
            "sector_type": "industry",
            "code": "A",
            "name": "测试",
            "pct_chg": 1.2,
            "main_net": 100_000_000,
            "super_net": None,
            "big_net": None,
            "mid_net": None,
            "small_net": None,
            "raw": "{}",
        }]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "flow.db"
            output_dir = root / "data"
            with patch("collector.providers.fetch_sector_snapshot", return_value=rows):
                written = collector.run_once(
                    db_path=db_path,
                    output_dir=output_dir,
                    config={"provider": "sina", "watchlist": ["测试"]},
                    now=datetime(2026, 8, 29, 9, 31, tzinfo=CN),
                )

            output = output_dir / "2026-08-29.json"
            self.assertEqual(written, 2)
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["series"][0]["data"][0], 1.0)
            self.assertEqual(len(db.fetch_for_date("2026-08-29", db_path=db_path)), 1)

    def test_viewer_contains_live_date_and_polling_contract(self):
        source = Path("web/viewer.html").read_text(encoding="utf-8")
        self.assertIn("Asia/Shanghai", source)
        self.assertIn("setInterval(loadData, 60000)", source)
        self.assertIn("dateParam === 'mock'", source)
        self.assertIn("新浪板块净流入", source)
        for label in ("曲线图", "排序图", "赛车图", "导出 CSV", "导出图片", "同花顺"):
            self.assertIn(label, source)
        self.assertIn("devicePixelRatio", source)
        for excluded in ("个股池", "板块池", "工具箱", "我的"):
            self.assertNotIn(excluded, source)

    def test_viewer_gives_flow_chart_more_vertical_space_and_avoids_label_overlap(self):
        source = Path("web/viewer.html").read_text(encoding="utf-8")
        self.assertIn("height: min(72vh, 760px)", source)
        self.assertIn("min-height: 560px", source)
        self.assertIn("height: 68vh; min-height: 500px", source)
        self.assertIn("moveOverlap: 'shiftY'", source)

    def test_config_watchlist_matches_requested_sector_selection(self):
        config = export.load_config(Path("config.yaml"))
        names = [item if isinstance(item, str) else item["name"] for item in config["watchlist"]]
        for name in ("创新药", "半导体设备", "半导体", "芯片", "黄金", "白银", "石油"):
            self.assertIn(name, names)
        for name in ("罕见病", "中药", "减速器"):
            self.assertNotIn(name, names)

    def test_mock_data_uses_configured_watchlist_names(self):
        config = export.load_config(Path("config.yaml"))
        configured = [item if isinstance(item, str) else item["name"] for item in config["watchlist"]]
        self.assertEqual([item["name"] for item in mock_data.build()["series"]], configured)


if __name__ == "__main__":
    unittest.main()
