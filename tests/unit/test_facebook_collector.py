"""
Unit tests for FacebookGraphCollector.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.crawler.facebook_collector import FacebookGraphCollector


class TestFacebookGraphCollector(unittest.TestCase):

    def setUp(self):
        self.collector = FacebookGraphCollector(access_token="fake_test_token")

    @patch("requests.get")
    def test_get_page_feed(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "123_456",
                    "message": "Historical post about Father Yod and the Source Family restaurant in 1971.",
                    "created_time": "2024-01-15T12:00:00+0000",
                    "permalink_url": "https://facebook.com/123/posts/456",
                    "from": {"name": "Historical Society", "id": "123"},
                }
            ],
            "paging": {}
        }
        mock_get.return_value = mock_response

        posts = self.collector.get_page_feed("123", limit=10)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["id"], "123_456")
        self.assertIn("Father Yod", posts[0]["message"])

    @patch("requests.get")
    def test_collect_page_research(self, mock_get):
        # Mock feed and comments
        def side_effect(url, params=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            if "feed" in url:
                resp.json.return_value = {
                    "data": [
                        {
                            "id": "123_456",
                            "message": "Jim Baker opened The Source in Los Angeles.",
                            "created_time": "2023-05-10T10:00:00+0000",
                            "permalink_url": "https://facebook.com/123/posts/456",
                            "from": {"name": "LA History Page", "id": "123"},
                        }
                    ],
                    "paging": {}
                }
            elif "comments" in url:
                resp.json.return_value = {
                    "data": [
                        {
                            "id": "c_1",
                            "message": "I remember eating there back in 1974.",
                            "created_time": "2023-05-10T11:00:00+0000",
                            "from": {"name": "John Doe", "id": "u1"},
                        }
                    ],
                    "paging": {}
                }
            else:
                resp.json.return_value = {"id": "123", "name": "LA History Page"}
            return resp

        mock_get.side_effect = side_effect

        pages = self.collector.collect_page_research("123", include_comments=True)
        self.assertEqual(len(pages), 1)
        self.assertIn("Jim Baker", pages[0].text)
        self.assertIn("John Doe", pages[0].text)
        self.assertEqual(pages[0].author, "LA History Page")


if __name__ == "__main__":
    unittest.main()
