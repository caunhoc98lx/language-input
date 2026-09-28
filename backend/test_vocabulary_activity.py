import sqlite3
import unittest
from datetime import datetime, timezone
from vocabulary_activity import vocabulary_activity


class VocabularyActivityTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE reviews (user_id INT, vocabulary_id INT, reviewed_at TEXT)")
        self.now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.conn.close()

    def test_unique_words_local_midnight_and_user_scope(self):
        self.conn.executemany("INSERT INTO reviews VALUES (?, ?, ?)", [
            (1, 10, "2026-09-27T16:59:00+00:00"),
            (1, 10, "2026-09-27T17:00:00+00:00"),
            (1, 10, "2026-09-28T01:00:00+00:00"),
            (1, 11, "2026-09-28T02:00:00"),
            (2, 12, "2026-09-28T02:00:00+00:00"),
            (1, 13, "2026-09-28T17:00:00+00:00"),
        ])
        result = vocabulary_activity(self.conn, {"id": 1, "timezone": "Asia/Bangkok"}, self.now)
        self.assertEqual(len(result["days"]), 30)
        self.assertEqual(result["days"][-1], {"date": "2026-09-28", "words": 2, "reviews": 3})
        self.assertEqual(result["days"][-2]["words"], 1)
        self.assertEqual(result["days"][0]["words"], 0)

    def test_empty_and_invalid_timezone(self):
        result = vocabulary_activity(self.conn, {"id": 1, "timezone": "invalid"}, self.now)
        self.assertEqual(result["timezone"], "UTC")
        self.assertEqual(sum(day["words"] for day in result["days"]), 0)
        self.assertEqual(result["days"][0]["date"], "2026-08-30")


if __name__ == "__main__":
    unittest.main()
