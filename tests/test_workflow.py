import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from rubric import RUBRIC, weighted_score
from store import ROOT, Store, benchmark, load_dataset


def ratings(value):
    return dict.fromkeys(RUBRIC, value)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "test.sqlite3"
        self.store = Store(self.path, load_dataset()["id"])

    def test_weights_and_invalid_ratings(self):
        self.assertAlmostEqual(sum(entry[0] for entry in RUBRIC.values()), 1)
        self.assertEqual([weighted_score(ratings(n)) for n in (1, 3, 5)], [0, 50, 100])
        for bad in ({}, ratings(True), ratings(6), ratings(None)):
            with self.assertRaises(ValueError):
                weighted_score(bad)

    def test_reviewer_uniqueness_and_qa_independence(self):
        self.store.submit("arithmetic", "A", "Human", ratings(4), "Evidence")
        row = self.store.rows()[0]
        with self.assertRaises(ValueError):
            self.store.submit("arithmetic", "A", " human ", ratings(4), "Evidence")
        with self.assertRaises(ValueError):
            self.store.review(row["id"], "HUMAN", "Approved", "Evidence")
        self.store.review(row["id"], "QA", "Needs revision", "Missed the equation")
        self.assertEqual(self.store.rows()[0]["decision"], "Needs revision")
        self.assertEqual(Store(self.path, "another-dataset").rows(), [])
        self.assertEqual(benchmark(self.store.rows(), {"arithmetic"}), [])
        self.store.submit("arithmetic", "A", "Human", ratings(5), "Corrected the rationale")
        self.assertEqual(self.store.rows()[1]["supersedes"], row["id"])
        self.assertIsNone(self.store.rows()[1]["decision"])

    def test_paired_aggregation(self):
        entries = [("x", "A", 100, "Approved"), ("x", "A", 50, "Approved"),
                   ("x", "B", 25, "Approved"), ("y", "B", 90, "Approved"),
                   ("x", "A", 0, None), ("y", "A", 0, "Needs revision")]
        rows = [dict(case_id=c, candidate=k, score=s, decision=d) for c, k, s, d in entries]
        self.assertEqual(benchmark(rows, {"x", "y"}), [{"Case": "x", "A": 75, "B": 25}])
        self.assertEqual(benchmark(rows, {"y"}), [])

    def test_streamlit_workflow(self):
        with patch.dict(os.environ, {"BENCHMARK_DB": str(self.path), "BENCHMARK_DATASET": str(ROOT / "data/sample.json")}):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertIn("Illustrative dataset", app.info[0].value)
            for candidate in ("A", "B"):
                app.radio(key="candidate").set_value(candidate).run()
                app.text_input[0].set_value("annotator")
                app.text_area[0].set_value("Compared the response against its reference.")
                for rating in app.selectbox[2:]:
                    rating.set_value(4)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.success)
            app.radio(key="workspace").set_value("QA review").run()
            for _ in range(2):
                app.text_input[0].set_value("quality")
                app.selectbox[2].set_value("Approved")
                app.text_area[0].set_value("Verified the logged score and rationale.")
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.success)
            # A fresh session also verifies that reviews survive a browser reload.
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            app.radio(key="workspace").set_value("Dashboard").run()
            self.assertFalse(app.exception)
            metrics = {metric.label: metric.value for metric in app.metric}
            self.assertEqual(metrics["Paired case coverage"], "1 / 8")
            self.assertEqual(metrics["Response A mean"], "75.00 / 100")
            self.assertEqual(metrics["Response B mean"], "75.00 / 100")
            app.radio(key="workspace").set_value("Rubric").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe[0].value), len(RUBRIC))


