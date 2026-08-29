import unittest
from unittest.mock import patch

import requests

import sina


class FakeResponse:
    def __init__(self, payload, *, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SinaBoardFlowTests(unittest.TestCase):
    def test_normalize_board_row_maps_sina_fields_to_project_shape(self):
        row = {
            "category": "new_hghy",
            "name": "化工行业",
            "avg_changeratio": "0.0182874",
            "netamount": "6846717370.7400",
            "inamount": "43989020935.7700",
        }

        normalized = sina.normalize_board_row(row, "industry")

        self.assertEqual(normalized["sector_type"], "industry")
        self.assertEqual(normalized["code"], "new_hghy")
        self.assertEqual(normalized["name"], "化工行业")
        self.assertAlmostEqual(normalized["pct_chg"], 1.82874)
        self.assertEqual(normalized["main_net"], 6846717370.74)
        self.assertIsNone(normalized["super_net"])
        self.assertIn("化工行业", normalized["raw"])

    def test_category_mapping_covers_project_sector_types(self):
        self.assertEqual(sina.FENLEI_BY_TYPE["industry"], 0)
        self.assertEqual(sina.FENLEI_BY_TYPE["concept"], 1)

    def test_fetch_snapshot_paginates_and_deduplicates_by_board_code(self):
        session = FakeSession(
            [
                FakeResponse(
                    [
                        {"category": "A", "name": "甲", "avg_changeratio": 0, "netamount": 1},
                        {"category": "B", "name": "乙", "avg_changeratio": 0, "netamount": 2},
                    ]
                ),
                FakeResponse(
                    [
                        {"category": "B", "name": "乙", "avg_changeratio": 0, "netamount": 20},
                        {"category": "C", "name": "丙", "avg_changeratio": 0, "netamount": 3},
                    ]
                ),
                FakeResponse([]),
            ]
        )

        with patch("sina.time.sleep"):
            rows = sina.fetch_board_snapshot("industry", session=session, page_size=2)

        self.assertEqual([row["code"] for row in rows], ["A", "B", "C"])
        self.assertEqual(rows[1]["main_net"], 2.0)
        self.assertEqual([call[1]["page"] for call in session.calls], ["1", "2", "3"])

    def test_first_page_failure_raises_sina_error(self):
        session = FakeSession(
            [requests.RequestException("blocked") for _ in range(4)]
        )

        with patch("sina.time.sleep"):
            with self.assertRaises(sina.SinaError):
                sina.fetch_board_snapshot("concept", session=session)

    def test_later_page_failure_returns_first_page_as_partial_snapshot(self):
        session = FakeSession(
            [
                FakeResponse(
                    [
                        {"category": "A", "name": "甲", "avg_changeratio": 0, "netamount": 1},
                        {"category": "B", "name": "乙", "avg_changeratio": 0, "netamount": 2},
                    ]
                ),
                *[requests.RequestException("temporary") for _ in range(4)],
            ]
        )

        with patch("sina.time.sleep"):
            rows = sina.fetch_board_snapshot("industry", session=session, page_size=2)

        self.assertEqual([row["code"] for row in rows], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
