#!/usr/bin/env python3
"""MemoFlow CLI and simple interactive terminal UI."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from MemoFlow.config import DATA_DIR
from MemoFlow.db import init_db, get_connection, insert_record
from MemoFlow.brief_engine import generate_briefs
from MemoFlow.ask_engine import answer_ask


def handle_ingest(day):
    init_db(reset=(day == 1))
    conn = get_connection()
    cur = conn.cursor()

    day_file = os.path.join(DATA_DIR, "days", f"day-{day:02d}.jsonl")
    count = 0
    if os.path.isfile(day_file):
        with open(day_file, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    insert_record(conn, json.loads(line), day)
                    count += 1

    if day > 1:
        feedback_file = os.path.join(DATA_DIR, "feedback", f"day-{day-1:02d}.jsonl")
        if os.path.isfile(feedback_file):
            with open(feedback_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    fb = json.loads(line)
                    cur.execute(
                        """INSERT INTO feedback
                        (day, person, type, words, meeting, topic, verdict)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (fb.get("day"), fb.get("person"), fb.get("type"),
                         fb.get("words"), fb.get("meeting"), fb.get("topic"),
                         fb.get("verdict")),
                    )
                    if fb.get("type") == "forget":
                        cur.execute(
                            "INSERT INTO forgets (person, what) VALUES (?, ?)",
                            (fb.get("person"), fb.get("words")),
                        )

    conn.commit()
    conn.close()
    print(json.dumps({"ok": True, "day": day, "records": count}))


def handle_brief(person, date):
    print(json.dumps(generate_briefs(person, date), ensure_ascii=False))


def handle_ask(person, at, ask):
    print(json.dumps(answer_ask(person, at, ask), ensure_ascii=False))


def handle_forget(person, what):
    init_db(reset=False)
    conn = get_connection()
    conn.execute("INSERT INTO forgets (person, what) VALUES (?, ?)", (person, what))
    conn.commit()
    conn.close()
    print(json.dumps({"ok": True}))


def main():
    ap = argparse.ArgumentParser(
        description="MemoFlow: workspace memory assistant. Run without a command to open the interactive UI."
    )
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("ingest", help="Ingest one bundled dataset day")
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

    sub.add_parser("tui", help="Open the interactive file-and-question UI")

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
