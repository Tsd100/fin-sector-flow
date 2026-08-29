import unittest
from unittest.mock import Mock, patch

import requests

import ths


INDUSTRY_PAGE_1 = """
<div class="page_info">1/2</div>
<table><tbody>
<tr><td>1</td><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881101/">消费电子</a></td><td>5983.64</td><td>2.03%</td><td>86.85</td><td>87.11</td><td>-0.26</td><td>95</td><td><a href="http://stockpage.10jqka.com.cn/000001/">示例股</a></td><td>5.0%</td><td>10.0</td></tr>
<tr><td>2</td><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881102/">中药</a></td><td>2977.40</td><td>-2.65%</td><td>29.00</td><td>40.11</td><td>-11.11</td><td>72</td><td><a href="http://stockpage.10jqka.com.cn/000002/">示例股2</a></td><td>-1.0%</td><td>8.0</td></tr>
</tbody></table>
"""

INDUSTRY_PAGE_2 = """
<div class="page_info">2/2</div>
<table><tbody>
<tr><td>1</td><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881101/">消费电子</a></td><td>5983.64</td><td>2.03%</td><td>86.85</td><td>87.11</td><td>-0.26</td><td>95</td><td>示例股</td><td>5.0%</td><td>10.0</td></tr>
<tr><td>2</td><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881103/">半导体</a></td><td>5000.00</td><td>1.20%</td><td>40.00</td><td>35.00</td><td>5.00</td><td>100</td><td>示例股3</td><td>3.0%</td><td>12.0</td></tr>
</tbody></table>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class ThsFlowTests(unittest.TestCase):
    def test_parse_page_normalizes_board_values_and_code(self):
        rows, pages = ths.parse_page(INDUSTRY_PAGE_1, "industry")

        self.assertEqual(pages, 2)
        self.assertEqual(rows[0]["code"], "881101")
        self.assertEqual(rows[0]["name"], "消费电子")
        self.assertEqual(rows[0]["pct_chg"], 2.03)
        self.assertEqual(rows[0]["main_net"], -26_000_000)
        self.assertEqual(rows[0]["sector_type"], "industry")
        self.assertEqual(rows[0]["raw"], "86.85,87.11,-0.26")

    def test_fetch_snapshot_paginates_deduplicates_and_uses_concept_path(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse(INDUSTRY_PAGE_1),
            FakeResponse(INDUSTRY_PAGE_2),
        ]

        rows = ths.fetch_board_snapshot("industry", session=session)

        self.assertEqual([row["code"] for row in rows], ["881101", "881102", "881103"])
        calls = session.get.call_args_list
        self.assertIn("hyzjl", calls[0].args[0])
        self.assertIn("/ajax/1/free/1/", calls[0].args[0])
        self.assertIn("/page/2/ajax/1/free/1/", calls[1].args[0])

        concept_session = Mock()
        concept_session.get.return_value = FakeResponse(INDUSTRY_PAGE_1)
        ths.fetch_board_snapshot("concept", session=concept_session)
        self.assertIn("gnzjl", concept_session.get.call_args.args[0])

    def test_later_page_failure_returns_first_page_as_partial_snapshot(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse(INDUSTRY_PAGE_1),
            requests.RequestException("temporary"),
            requests.RequestException("temporary"),
            requests.RequestException("temporary"),
            requests.RequestException("temporary"),
        ]

        with patch("ths.time.sleep"):
            rows = ths.fetch_board_snapshot("industry", session=session)

        self.assertEqual([row["code"] for row in rows], ["881101", "881102"])

    def test_first_page_failure_raises_ths_error(self):
        session = Mock()
        session.get.side_effect = requests.RequestException("blocked")

        with patch("ths.time.sleep"), self.assertRaises(ths.ThsError):
            ths.fetch_board_snapshot("concept", session=session)


if __name__ == "__main__":
    unittest.main()
