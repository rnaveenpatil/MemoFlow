"""Simple interactive terminal UI for MemoFlow.

Uses the operating-system file picker when tkinter is available, with a
terminal path prompt as a fallback. No third-party TUI dependency required.
"""
import json
import os
from datetime import datetime, timezone

from MemoFlow.ask_engine import answer_ask
from MemoFlow.config import PEOPLE_BY_ID
from MemoFlow.db import get_connection, init_db, insert_record


def _select_jsonl_file():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select MemoFlow JSONL data file",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            return path
    except Exception:
        pass

    return input("Enter the path to a .jsonl file: ").strip().strip('"')


def _ingest_file(path, day):
    if not path or not os.path.isfile(path):
        print("File not found. Select a valid JSONL file.")
        return 0

    init_db(reset=False)
    conn = get_connection()
    count = 0
    errors = []
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict) or not record.get("id"):
                        raise ValueError("record must be a JSON object with an id")
                    insert_record(conn, record, day)
                    count += 1
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    errors.append(f"Line {line_number}: {exc}")
        conn.commit()
    except OSError as exc:
        conn.rollback()
        print(f"Could not read file: {exc}")
        return 0
    finally:
        conn.close()

    print(f"\nImported {count} records from: {os.path.basename(path)}")
    if errors:
        print(f"Skipped {len(errors)} invalid line(s). First issue: {errors[0]}")
    return count


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
    print("\nMemoFlow is ready. Type a question, /person to change person, or /exit to quit.")
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
        if question.casefold() == "/person":
            person = _choose_person()
            continue
        if question.casefold() == "/file":
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
        print("\n1. Select and add a JSONL file")
        print("2. Ask a question")
        print("3. Exit")
        choice = input("\nChoose an option: ").strip()

        if choice == "1":
            path = _select_jsonl_file()
            if not path:
                print("No file selected.")
                continue
            day_text = input("Dataset day number (for example, 1): ").strip()
            try:
                day = int(day_text)
                if day < 1:
                    raise ValueError
            except ValueError:
                print("Day must be a positive number. File was not imported.")
                continue
            _ingest_file(path, day)
            if person is None:
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
