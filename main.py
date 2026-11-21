#!/usr/bin/env python3
"""MemoFlow CLI and simple interactive terminal UI."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from MemoFlow.config import DATA_DIR
from MemoFlow.db import init_db, get_connection, insert_record, sync_workspace_metadata
from MemoFlow.brief_engine import generate_briefs
from MemoFlow.ask_engine import answer_ask


def _read_jsonl(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or not record.get("id"):
                raise ValueError(f"{path}:{line_number}: expected a JSON object with an id")
            yield record


def _ingest_feedback(conn, feedback_day):
    path = os.path.join(DATA_DIR, "feedback", f"day-{feedback_day:02d}.jsonl")
    if not os.path.isfile(path):
        return 0
    count = 0
    for fb in _read_jsonl(path):
        values = (fb.get("day", feedback_day), fb.get("person"), fb.get("type"), fb.get("words"),
                  fb.get("meeting"), fb.get("topic"), fb.get("verdict"))
        available_day = feedback_day + 1
        exists = conn.execute(
            """SELECT 1 FROM feedback WHERE day IS ? AND person IS ? AND type IS ?
               AND words IS ? AND meeting IS ? AND topic IS ? AND verdict IS ? LIMIT 1""",
            values
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO feedback
            (day, person, type, words, meeting, topic, verdict, available_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", values + (available_day,)
        )
        if fb.get("type") == "forget":
            forget_exists = conn.execute(
                "SELECT 1 FROM forgets WHERE person = ? AND what = ? LIMIT 1",
                (fb.get("person"), fb.get("words"))
            ).fetchone()
            if not forget_exists:
                conn.execute(
                    "INSERT INTO forgets (person, what, day) VALUES (?, ?, ?)",
                    (fb.get("person"), fb.get("words"), available_day)
                )
        count += 1
    return count


def handle_ingest(day):
    if day < 1:
        raise ValueError("Day must be a positive integer.")
    init_db(reset=False)
    conn = get_connection()
    sync_workspace_metadata(conn)
    imported = {}
    feedback_count = 0
    try:
        day_dir = os.path.join(DATA_DIR, "days")
        missing = [
            d for d in range(1, day + 1)
            if not os.path.isfile(os.path.join(day_dir, f"day-{d:02d}.jsonl"))
            and not conn.execute("SELECT 1 FROM records WHERE day = ? LIMIT 1", (d,)).fetchone()
        ]
        if missing:
            raise FileNotFoundError(
                "Cannot ingest cumulatively; missing day file(s): "
                + ", ".join(str(d) for d in missing)
            )

        # Replaying an earlier day must not inherit future rows from a previous run.
        future_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM records WHERE day > ?", (day,)
        ).fetchall()]
        if future_ids:
            conn.executemany("DELETE FROM records_fts WHERE id = ?", [(rid,) for rid in future_ids])
        conn.execute("DELETE FROM records WHERE day > ?", (day,))
        conn.execute("DELETE FROM task_changes WHERE day > ?", (day,))
        conn.execute("DELETE FROM meetings WHERE day > ?", (day,))
        conn.execute("DELETE FROM feedback WHERE available_day > ?", (day,))
        conn.execute("DELETE FROM forgets WHERE day > ?", (day,))
        conn.execute("DELETE FROM promises WHERE day > ?", (day,))
        conn.execute(
            "UPDATE promises SET fulfilled = 0, fulfilled_day = NULL "
            "WHERE fulfilled_day > ?", (day,)
        )
        conn.execute("DELETE FROM tasks WHERE last_day > ?", (day,))

        for current_day in range(1, day + 1):
            path = os.path.join(day_dir, f"day-{current_day:02d}.jsonl")
            count = 0
            if os.path.isfile(path):
                for record in _read_jsonl(path):
                    exists = conn.execute(
                        "SELECT 1 FROM records WHERE id = ?", (record["id"],)
                    ).fetchone()
                    if exists:
                        continue
                    insert_record(conn, record, current_day)
                    count += 1
            imported[current_day] = count
            if current_day > 1:
                feedback_count += _ingest_feedback(conn, current_day - 1)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    print(json.dumps({
        "ok": True,
        "through_day": day,
        "new_records_by_day": imported,
        "new_feedback": feedback_count
    }))


def handle_brief(person, date):
    print(json.dumps(generate_briefs(person, date), ensure_ascii=False))


def handle_ask(person, at, ask):
    print(json.dumps(answer_ask(person, at, ask), ensure_ascii=False))


def handle_forget(person, what):
    init_db(reset=False)
    conn = get_connection()
    current_day = conn.execute("SELECT MAX(day) AS day FROM records").fetchone()["day"]
    conn.execute("INSERT INTO forgets (person, what, day) VALUES (?, ?, ?)", (person, what, current_day))
    conn.commit()
    conn.close()
    print(json.dumps({"ok": True}))


def main():
    ap = argparse.ArgumentParser(
        description="MemoFlow: workspace memory assistant. Run without a command to open the interactive terminal chat."
    )
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("ingest", help="Cumulatively ingest bundled data through a day")
    s.add_argument("--day", type=int, required=True)

    s = sub.add_parser("brief", help="Generate a person's daily brief")
    s.add_argument("--person", required=True)
    s.add_argument("--date", required=True)

    s = sub.add_parser("ask", help="Ask a question about workspace records")
    s.add_argument("--person", required=True)
    s.add_argument("--at", required=True)
    s.add_argument("--ask", required=True)

    s = sub.add_parser("forget", help="Store a forget request")
    s.add_argument("--person", required=True)
    s.add_argument("--what", required=True)

    sub.add_parser("tui", help="Open the interactive terminal chat")

    args = ap.parse_args()

    if args.cmd is None or args.cmd == "tui":
        from MemoFlow.tui import run_tui
        run_tui()
    elif args.cmd == "ingest":
        handle_ingest(args.day)
    elif args.cmd == "brief":
        handle_brief(args.person, args.date)
    elif args.cmd == "ask":
        handle_ask(args.person, args.at, args.ask)
    elif args.cmd == "forget":
        handle_forget(args.person, args.what)


if __name__ == "__main__":
    main()
