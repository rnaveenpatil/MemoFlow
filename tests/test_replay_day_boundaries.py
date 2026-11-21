"""Regression tests for cumulative replay-day isolation."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys

# The repository itself is the MemoFlow package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MemoFlow.db import get_connection, init_db
from MemoFlow.ask_engine import _load_people, _visible_record_candidates, _task_catalog
from MemoFlow.brief_engine import _model_change_items
from unittest.mock import patch


class ReplayDayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite3")
        init_db(db_path=self.db_path)
        self.conn = get_connection(self.db_path)
        self.conn.execute(
            "INSERT INTO people(person_id,org,name,role,raw_json) VALUES(?,?,?,?,?)",
            ("alice", "orgA", "Alice", "manager", "{}"),
        )
        self.conn.execute(
            "INSERT INTO people(person_id,org,name,role,raw_json) VALUES(?,?,?,?,?)",
            ("bob", "orgA", "Bob", "manager", "{}"),
        )
        self._record("r1", 1, "alice", "dayonealpha", "task-old", "2026-11-01T10:00:00Z")
        self._record("r3", 3, "bob", "futureonlyomega", "task-new", "2026-11-03T10:00:00Z")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _record(self, rid, day, author, body, task_id, at):
        record = {
            "id": rid, "day": day, "org": "orgA", "type": "task",
            "at": at, "author": author, "client": "clientA",
            "visibility": "team", "readers": [], "task_id": task_id,
            "title": body, "owner": author, "due": "2026-12-01",
            "status": "todo", "body": body,
        }
        raw = json.dumps(record)
        self.conn.execute(
            """INSERT INTO records
               (id,day,org,type,at,author,client,visibility,task_id,title,owner,due,status,body,raw_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, day, "orgA", "task", at, author, "clientA", "team",
             task_id, body, author, "2026-12-01", "todo", body, raw),
        )
        self.conn.execute(
            """INSERT INTO records_fts(id,title,body,author,client,subject,channel)
               VALUES(?,?,?,?,?,?,?)""",
            (rid, body, body, author, "clientA", "", ""),
        )

    def test_people_directory_excludes_future_only_people(self):
        people = _load_people(self.conn, "orgA", dataset_day=1)
        self.assertEqual([p["id"] for p in people], ["alice"])

    def test_fts_retrieval_excludes_future_day_records(self):
        rows = _visible_record_candidates(
            self.conn, "alice", "orgA", "2026-11-05T00:00:00Z",
            "futureonlyomega", dataset_day=1,
        )
        self.assertEqual(rows, [])

    def test_task_catalog_is_cumulative_but_never_future(self):
        tasks = _task_catalog(
            self.conn, "2026-11-05T00:00:00Z", "orgA", "alice",
            dataset_day=1,
        )
        self.assertEqual([task["id"] for task in tasks], ["task-old"])


    def test_people_directory_excludes_private_people_from_other_users(self):
        private_record = {
            "id": "private1", "day": 1, "org": "orgA", "type": "note",
            "at": "2026-11-01T11:00:00Z", "author": "bob", "client": "clientA",
            "visibility": "private", "readers": [], "task_id": None,
            "title": "private", "owner": None, "due": None, "status": None,
            "body": "private detail",
        }
        self.conn.execute(
            """INSERT INTO records
               (id,day,org,type,at,author,client,visibility,title,body,raw_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("private1", 1, "orgA", "note", private_record["at"], "bob",
             "clientA", "private", "private", "private detail", json.dumps(private_record)),
        )
        self.conn.commit()
        people = _load_people(self.conn, "orgA", dataset_day=1, person="alice")
        self.assertEqual([p["id"] for p in people], ["alice"])

    def test_model_promise_extraction_accepts_hinglish_and_validates_source(self):
        evidence = [{
            "id": "mail1", "type": "chat", "at": "2026-11-02T08:00:00Z",
            "author": "alice", "author_local_date": "2026-11-02",
            "title": "Delivery", "body": "kal tak bhej dungi",
        }]
        response = {
            "text": json.dumps({
                "changes": [],
                "promises": [{
                    "owner": "alice", "what": "billing report",
                    "due": "2026-11-03", "sources": ["mail1"]
                }]
            }),
            "usage": {"input_tokens": 100, "output_tokens": 30, "cost_usd": 0.0, "ms": 5},
        }
        with patch("MemoFlow.brief_engine.call_llm", return_value=response):
            changes, promises, usage = _model_change_items(evidence, [], "meeting1", "clientA")
        self.assertEqual(changes, [])
        self.assertEqual(len(promises), 1)
        self.assertEqual(promises[0]["owner"], "alice")
        self.assertEqual(promises[0]["due"], "2026-11-03")
        self.assertEqual(promises[0]["sources"], ["mail1"])
        self.assertEqual(usage["input_tokens"], 100)

    def test_model_cannot_invent_promise_source_or_owner(self):
        evidence = [{
            "id": "mail1", "type": "chat", "at": "2026-11-02T08:00:00Z",
            "author": "alice", "author_local_date": "2026-11-02",
            "title": "Delivery", "body": "will send",
        }]
        response = {
            "text": json.dumps({
                "changes": [],
                "promises": [{
                    "owner": "bob", "what": "billing report",
                    "due": "2026-11-03", "sources": ["invented-record"]
                }]
            }),
            "usage": {"input_tokens": 100, "output_tokens": 30, "cost_usd": 0.0, "ms": 5},
        }
        with patch("MemoFlow.brief_engine.call_llm", return_value=response):
            changes, promises, usage = _model_change_items(evidence, [], "meeting1", "clientA")
        self.assertEqual(promises, [])

    def test_feedback_is_not_visible_before_its_availability_day(self):
        self.conn.execute(
            """INSERT INTO feedback(day,person,type,words,available_day)
               VALUES(1,'alice','correction','billing owner changed',2)"""
        )
        self.conn.commit()
        day_one = self.conn.execute(
            "SELECT words FROM feedback WHERE person='alice' AND available_day <= 1"
        ).fetchall()
        day_two = self.conn.execute(
            "SELECT words FROM feedback WHERE person='alice' AND available_day <= 2"
        ).fetchall()
        self.assertEqual(day_one, [])
        self.assertEqual(len(day_two), 1)

    def test_schema_has_day_provenance_columns(self):
        forget_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(forgets)")}
        promise_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(promises)")}
        feedback_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(feedback)")}
        self.assertIn("day", forget_cols)
        self.assertIn("fulfilled_day", promise_cols)
        self.assertIn("available_day", feedback_cols)


if __name__ == "__main__":
    unittest.main()
