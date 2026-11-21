"""Simple interactive terminal UI for MemoFlow.

The selected filename identifies the target dataset day. Import is cumulative:
selecting Day N imports available days 1..N and never imports later days.
"""
import json
import os
import re
from datetime import datetime, timezone

from MemoFlow.ask_engine import answer_ask
from MemoFlow.config import DATA_DIR, PEOPLE_BY_ID
from MemoFlow.db import get_connection, init_db, insert_record, sync_workspace_metadata


_DAY_RE = re.compile(r"(?:^|[^a-z0-9])day[-_ ]?0*(\d+)(?:[^0-9]|$)", re.I)


def _select_jsonl_file():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select a MemoFlow day file",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            return path
    except Exception:
        pass
    return input("Enter the path to a day-N .jsonl file: ").strip().strip('"')


def _day_number(path):
    """Infer the challenge day from the selected file name; never guess by selection order."""
    match = _DAY_RE.search(os.path.basename(path))
    if match:
        return int(match.group(1))
    raise ValueError(
        "Cannot identify the dataset day from this filename. Rename it to include "
        "'day-01', 'day-02', etc., then select it again."
    )


def _candidate_day_paths(selected_path, day, data_dir=None):
    filename = os.path.basename(selected_path)
    match = _DAY_RE.search(filename)
    if not match:
        return []
    prefix = filename[:match.start()]
    suffix = filename[match.end():]
    # Preserve common naming styles such as day-02.jsonl and Day 2.jsonl.
    names = [
        f"day-{day:02d}.jsonl",
        f"day-{day}.jsonl",
        f"Day {day}.jsonl",
        f"Day-{day}.jsonl",
        f"day_{day:02d}.jsonl",
        f"{prefix}day-{day:02d}{suffix}",
    ]
    data_dir = data_dir or DATA_DIR
    directories = [os.path.dirname(os.path.abspath(selected_path)),
                   os.path.join(data_dir, "days"), data_dir]
    seen = set()
    for directory in directories:
        for name in names:
            candidate = os.path.abspath(os.path.join(directory, name))
            if candidate not in seen and os.path.isfile(candidate):
                seen.add(candidate)
                yield candidate


def _load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{os.path.basename(path)} line {line_number}: {exc}") from exc
            if not isinstance(record, dict) or not record.get("id"):
                raise ValueError(
                    f"{os.path.basename(path)} line {line_number}: expected a JSON object with an id"
                )
            records.append(record)
    return records


def _find_metadata_dir(selected_path):
    """Find the challenge pack metadata next to the selected day file."""
    current = os.path.dirname(os.path.abspath(selected_path))
    for _ in range(7):
        if os.path.isfile(os.path.join(current, "people.json")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return DATA_DIR


def _ingest_feedback(conn, feedback_day, data_dir=None):
    data_dir = data_dir or DATA_DIR
    feedback_path = os.path.join(data_dir, "feedback", f"day-{feedback_day:02d}.jsonl")
    if not os.path.isfile(feedback_path):
        return 0
    imported = 0
    with open(feedback_path, "r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            feedback = json.loads(line)
            values = (
                feedback.get("day"), feedback.get("person"), feedback.get("type"),
                feedback.get("words"), feedback.get("meeting"), feedback.get("topic"),
                feedback.get("verdict")
            )
            exists = conn.execute(
                """SELECT 1 FROM feedback WHERE day IS ? AND person IS ? AND type IS ?
                   AND words IS ? AND meeting IS ? AND topic IS ? AND verdict IS ? LIMIT 1""",
                values
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO feedback
                   (day, person, type, words, meeting, topic, verdict)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""", values
            )
            if feedback.get("type") == "forget":
                forget_exists = conn.execute(
                    "SELECT 1 FROM forgets WHERE person = ? AND what = ? LIMIT 1",
                    (feedback.get("person"), feedback.get("words"))
                ).fetchone()
                if not forget_exists:
                    conn.execute(
                        "INSERT INTO forgets (person, what) VALUES (?, ?)",
                        (feedback.get("person"), feedback.get("words"))
                    )
            imported += 1
    return imported


def _ingest_cumulative(selected_path):
    if not selected_path or not os.path.isfile(selected_path):
        print("File not found. Select a valid JSONL file.")
        return False

    try:
        target_day = _day_number(selected_path)
        if target_day < 1:
            raise ValueError("Dataset day must be at least 1.")

        metadata_dir = _find_metadata_dir(selected_path)
        paths_by_day = {}
        for day in range(1, target_day + 1):
            matches = list(_candidate_day_paths(selected_path, day, data_dir=metadata_dir))
            if day == target_day:
                selected = os.path.abspath(selected_path)
                if selected not in matches:
                    matches.insert(0, selected)
            if matches:
                paths_by_day[day] = matches[0]

        # Earlier days may already be present in the persistent database.
        init_db(reset=False)
        conn = get_connection()
        try:
            sync_workspace_metadata(conn, data_dir=metadata_dir)
            existing_days = {
                row["day"] for row in conn.execute(
                    "SELECT DISTINCT day FROM records WHERE day IS NOT NULL"
                ).fetchall()
            }
            missing = [
                day for day in range(1, target_day + 1)
                if day not in paths_by_day and day not in existing_days
            ]
            if missing:
                raise ValueError(
                    "Cannot build cumulative history. Missing earlier day file(s): "
                    + ", ".join(str(day) for day in missing)
                    + ". Keep day-01.jsonl through the selected day in the same folder "
                    "or in the configured dataset/data/days folder."
                )

            imported = {}
            imported_feedback = 0
            for day in range(1, target_day + 1):
                path = paths_by_day.get(day)
                if not path:
                    imported[day] = 0
                    continue
                records = _load_jsonl(path)
                added = 0
                for record in records:
                    # Avoid replaying derived task-change/promise history on repeated imports.
                    exists = conn.execute(
                        "SELECT 1 FROM records WHERE id = ?", (record["id"],)
                    ).fetchone()
                    if exists:
                        continue
                    insert_record(conn, record, day)
                    added += 1
                imported[day] = added
                if day > 1:
                    imported_feedback += _ingest_feedback(conn, day - 1, data_dir=metadata_dir)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        total = sum(imported.values())
        summary = ", ".join(f"Day {day}: +{count}" for day, count in imported.items())
        print(f"\nCumulative import complete through Day {target_day}.")
        print(summary)
        print(f"New records imported: {total}")
        conn = get_connection()
        try:
            total_in_db = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            people_in_db = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
            clients_in_db = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        finally:
            conn.close()
        print(f"New feedback entries imported: {imported_feedback}")
        print(f"SQLite now contains {total_in_db} records, {people_in_db} people and {clients_in_db} clients.")
        print("No future-day files were read.")
        return True
    except (OSError, ValueError) as exc:
        print(f"Import failed: {exc}")
        return False


def _ask_loop(person):
    print("\nMemoFlow is ready. Chat naturally. Mention people and clients by name.")
    print("Commands: /file to load more data, /exit to quit.")
    print("Try: 'What happened on Nov 4?', 'What was true as of Friday?', or 'Summarize Nov 1 to Nov 5'.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting MemoFlow.")
            return
        if not question:
            continue
        if question.casefold() in {"/exit", "exit", "quit"}:
            return
        if question.casefold() == "/file":
            return "select_file"
        asked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            result = answer_ask(person, asked_at, question)
        except Exception as exc:
            print(f"MemoFlow error: {exc}")
            continue
        if result.get("refused"):
            print(f"MemoFlow: I can't provide that: {result['refused'].get('reason', 'Not authorized.')}")
        elif result.get("clarify"):
            clarification = result["clarify"]
            print(f"MemoFlow: {clarification.get('question', 'Can you clarify?')}")
            for option in clarification.get("options", []):
                print(f"  - {option.get('text', option.get('id', 'Option'))}")
        elif result.get("answer"):
            print(f"MemoFlow: {result['answer'].get('text', 'No answer returned.')}")
            sources = result["answer"].get("sources") or []
            if sources:
                print("Sources: " + ", ".join(sources))
        else:
            print("MemoFlow: I couldn't find a reliable answer in the records available to this workspace.")


def _ask_loop(person):
    print("\nMemoFlow is ready. Chat naturally. Use /file to add more data, /whoami to see your session, or /exit to quit.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting MemoFlow.")
            return

        if not question:
            continue
        command = question.casefold()
        if command in {"/exit", "exit", "quit"}:
            return
        if command == "/whoami":
            print(f"MemoFlow: You are signed in as {PEOPLE_BY_ID.get(person, {}).get('name', 'Unknown')}.")
            continue
        if command == "/file":
            return "select_file"

        asked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            result = answer_ask(person, asked_at, question)
        except Exception as exc:
            print(f"MemoFlow error: {exc}")
            continue

        if result.get("refused"):
            print(f"MemoFlow: I can't provide that: {result['refused'].get('reason', 'Not authorized.')}")
        elif result.get("clarify"):
            clarification = result["clarify"]
            print(f"MemoFlow: {clarification.get('question', 'Can you clarify?')}")
            for option in clarification.get("options", []):
                print(f"  - {option.get('text', option.get('id', 'Option'))}")
        elif result.get("answer"):
            print(f"MemoFlow: {result['answer'].get('text', 'No answer returned.')}")
            sources = result["answer"].get("sources") or []
            if sources:
                print("Sources: " + ", ".join(sources))
        else:
            print("MemoFlow: I couldn't find a reliable answer in the records available to your account.")

def run_tui():
    init_db(reset=False)
    print("=" * 48)
    print("                 MEMOFLOW")
    print("       Your workspace memory assistant")
    print("=" * 48)
    print("Select a dataset file to load your workspace memory.")
    print("You do not need to enter employee names or internal IDs to start chatting.")

    while True:
        path = _select_jsonl_file()
        if not path:
            print("No file selected. Select a JSONL day file to begin.")
            continue
        if _ingest_cumulative(path):
            break

    # Workspace mode intentionally has no asserted employee identity.
    # The backend permits team-visible records only for this sentinel;
    # private and restricted records remain inaccessible.
    workspace_person = "__workspace__"
    while True:
        result = _ask_loop(workspace_person)
        if result == "select_file":
            path = _select_jsonl_file()
            if path:
                _ingest_cumulative(path)
            else:
                print("No file selected.")
            continue
        print("Goodbye.")
        return
