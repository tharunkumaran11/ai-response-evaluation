"""Dataset loading, review persistence, and paired benchmark summaries."""
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from statistics import mean

from rubric import VERSION, weighted_score

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "sample.json"


def load_dataset(path=DATA):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    if data["kind"] not in {"illustrative", "real"} or not data["id"].strip() or not data["cases"]:
        raise ValueError("Dataset requires an ID, kind, and at least one case.")
    for case in data["cases"]:
        if not case["id"].strip() or case["id"] in seen:
            raise ValueError("Case IDs must be non-empty and unique.")
        seen.add(case["id"])
        if not all(case[key].strip() for key in ("category", "prompt", "reference")):
            raise ValueError("Every case requires a category, prompt, and reference.")
        if set(case["responses"]) != {"A", "B"} or not all(v.strip() for v in case["responses"].values()):
            raise ValueError("Every case requires non-empty A and B responses.")
    return data


class Store:
    def __init__(self, path, dataset_id):
        self.path = path
        self.dataset_id = dataset_id
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, rubric TEXT NOT NULL,
                    case_id TEXT NOT NULL, candidate TEXT NOT NULL, reviewer TEXT NOT NULL,
                    scores TEXT NOT NULL, score REAL NOT NULL, rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    supersedes INTEGER UNIQUE REFERENCES reviews(id)
                );
                CREATE TABLE IF NOT EXISTS qa (
                    review_id INTEGER PRIMARY KEY REFERENCES reviews(id),
                    reviewer TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def submit(self, case_id, candidate, reviewer, scores, rationale):
        reviewer, rationale = reviewer.strip().casefold(), rationale.strip()
        if not reviewer or not rationale or candidate not in ("A", "B"):
            raise ValueError("Candidate, reviewer ID, and rationale are required.")
        with closing(self.connect()) as db, db:
            score = weighted_score(scores)
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                """SELECT r.id, q.decision FROM reviews r LEFT JOIN qa q ON q.review_id = r.id
                   WHERE r.dataset = ? AND r.rubric = ? AND r.case_id = ?
                     AND r.candidate = ? AND r.reviewer = ? ORDER BY r.id DESC LIMIT 1""",
                (self.dataset_id, VERSION, case_id, candidate, reviewer),
            ).fetchone()
            if prior is not None and prior["decision"] != "Needs revision":
                raise ValueError("This reviewer already has a pending or approved score for this response.")
            db.execute(
                """INSERT INTO reviews (dataset, rubric, case_id, candidate, reviewer,
                                        scores, score, rationale, supersedes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.dataset_id, VERSION, case_id, candidate, reviewer, json.dumps(scores),
                 score, rationale, prior["id"] if prior else None),
            )

    def review(self, review_id, reviewer, decision, note):
        reviewer, note = reviewer.strip().casefold(), note.strip()
        if not reviewer or not note or decision not in ("Approved", "Needs revision"):
            raise ValueError("QA reviewer ID, decision, and note are required.")
        with closing(self.connect()) as db, db:
            owner = db.execute(
                "SELECT reviewer FROM reviews WHERE id = ? AND dataset = ? AND rubric = ?",
                (review_id, self.dataset_id, VERSION),
            ).fetchone()
            if owner is None or owner["reviewer"] == reviewer:
                raise ValueError("QA requires a different reviewer ID on an existing review.")
            db.execute("INSERT INTO qa (review_id, reviewer, decision, note) VALUES (?, ?, ?, ?)",
                       (review_id, reviewer, decision, note))

    def rows(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                """SELECT r.*, q.reviewer AS qa_reviewer, q.decision, q.note, q.created_at AS qa_at
                   FROM reviews r LEFT JOIN qa q ON q.review_id = r.id
                   WHERE r.dataset = ? AND r.rubric = ? ORDER BY r.id""",
                (self.dataset_id, VERSION),
            )]


def benchmark(rows, allowed_cases):
    approved = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["decision"] == "Approved" and row["case_id"] in allowed_cases:
            approved[row["case_id"]][row["candidate"]].append(row["score"])
    pairs = [
        {"Case": case_id, "A": mean(scores["A"]), "B": mean(scores["B"])}
        for case_id, scores in sorted(approved.items()) if scores["A"] and scores["B"]
    ]
    return pairs

