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
from MemoFlow.db import get_connection, init_db, insert_record


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


def _candidate_day_paths(selected_path, day):
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
    directories = [os.path.dirname(os.path.abspath(selected_path)),
                   os.path.join(DATA_DIR, "days")]
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


def _ingest_cumulative(selected_path):
    if not selected_path or not os.path.isfile(selected_path):
        print("File not found. Select a valid JSONL file.")
        return False

    try:
        target_day = _day_number(selected_path)
        if target_day < 1:
            raise ValueError("Dataset day must be at least 1.")

        paths_by_day = {}
        for day in range(1, target_day + 1):
            matches = list(_candidate_day_paths(selected_path, day))
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
        print("No future-day files were read.")
        return True
    except (OSError, ValueError) as exc:
        print(f"Import failed: {exc}")
        return False


def _choose_person():
    if not PEOPLE_BY_ID:
        return input("Person ID: ").strip()

    print("\nAvailable people:")
    for person_id, person in sorted(PEOPLE_BY_ID.items()):
        print(f"  {person_id:<8} {person.get('name', 'Unknown')} — {person.get('role', '')}")

    while True:
        person_id = input("\nYour person ID: ").strip()
        if person_id in PEOPLE_BY_ID:
            return person_id
        print("That ID is not in the loaded people list. Try again.")


def _ask_loop(person):
    print("\nMemoFlow is ready. Type a question, /person to change person, /file to add data, or /exit.")
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
        if command == "/person":
            person = _choose_person()
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
            print(f"MemoFlow: Request refused — {result['refused'].get('reason', 'Not authorized.')}")
        elif result.get("clarify"):
            clarification = result["clarify"]
            print(f"MemoFlow: {clarification.get('question', 'Can you clarify?')}")
            for option in clarification.get("options", []):
                print(f"  - {option.get('id')}: {option.get('text')}")
        elif result.get("answer"):
            print(f"MemoFlow: {result['answer'].get('text', 'No answer returned.')}")
            sources = result["answer"].get("sources") or []
            if sources:
                print("Sources: " + ", ".join(sources))
        else:
            print("MemoFlow: I couldn't find a reliable answer in the available records.")


def run_tui():
    print("=" * 48)
    print("                 MEMOFLOW")
    print("        Workspace memory assistant")
    print("=" * 48)

    person = _choose_person() if PEOPLE_BY_ID else None
    while True:
        print("\n1. Select and add a day file")
        print("2. Ask a question")
        print("3. Exit")
        choice = input("\nChoose an option: ").strip()

        if choice == "1":
            path = _select_jsonl_file()
            if not path:
                print("No file selected.")
                continue
            if _ingest_cumulative(path) and person is None:
                person = _choose_person()
        elif choice == "2":
            if person is None:
                person = _choose_person()
            result = _ask_loop(person)
            if result == "select_file":
                continue
        elif choice == "3":
            print("Goodbye.")
            return
        else:
            print("Choose 1, 2, or 3.")
