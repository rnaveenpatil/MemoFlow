"""MemoFlow interactive terminal chat.

All bundled day files are ingested into SQLite at startup. No desktop GUI or
file picker is used. The workspace session is deliberately team-only because
this CLI does not authenticate an individual employee.
"""
import json
import os
import re
from datetime import datetime, timezone

from MemoFlow.ask_engine import answer_ask
from MemoFlow.config import DATA_DIR
from MemoFlow.db import get_connection, init_db, insert_record, sync_workspace_metadata

_DAY_RE = re.compile(r"day[-_ ]?0*(\d+)", re.I)


def _load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{os.path.basename(path)} line {line_no}: {exc}") from exc
            if not isinstance(item, dict) or not item.get("id") or not item.get("at"):
                raise ValueError(f"{os.path.basename(path)} line {line_no}: each record needs id and at")
            rows.append(item)
    return rows


def _day_from_name(name):
    match = _DAY_RE.search(os.path.basename(name))
    return int(match.group(1)) if match else None


def _import_feedback(conn):
    feedback_dir = os.path.join(DATA_DIR, "feedback")
    if not os.path.isdir(feedback_dir):
        return 0
    added = 0
    for name in sorted(os.listdir(feedback_dir)):
        if not name.lower().endswith(".jsonl") or _day_from_name(name) is None:
            continue
        feedback_path = os.path.join(feedback_dir, name)
        with open(feedback_path, "r", encoding="utf-8-sig") as stream:
            feedback_rows = []
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    fb = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{name} line {line_no}: {exc}") from exc
                if not isinstance(fb, dict):
                    raise ValueError(f"{name} line {line_no}: feedback row must be a JSON object")
                feedback_rows.append(fb)
        for fb in feedback_rows:
            feedback_day = _day_from_name(name)\n            values = (fb.get("day", feedback_day), fb.get("person"), fb.get("type"), fb.get("words"),
                      fb.get("meeting"), fb.get("topic"), fb.get("verdict"))
            exists = conn.execute(
                """SELECT 1 FROM feedback WHERE day IS ? AND person IS ? AND type IS ?
                   AND words IS ? AND meeting IS ? AND topic IS ? AND verdict IS ? LIMIT 1""",
                values
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO feedback(day,person,type,words,meeting,topic,verdict)
                   VALUES(?,?,?,?,?,?,?)""", values
            )
            if str(fb.get("type", "")).casefold() == "forget" and fb.get("words"):
                forget_exists = conn.execute(
                    "SELECT 1 FROM forgets WHERE person = ? AND what = ? LIMIT 1",
                    (fb.get("person") or "*", fb["words"])
                ).fetchone()
                if not forget_exists:
                    conn.execute("INSERT INTO forgets(person,what,day) VALUES(?,?,?)",
                                 (fb.get("person") or "*", fb["words"], fb.get("day")))
            added += 1
    return added


def bootstrap_dataset():
    """Import every bundled day file into SQLite, without duplicating record IDs."""
    days_dir = os.path.join(DATA_DIR, "days")
    if not os.path.isdir(days_dir):
        raise FileNotFoundError(f"Dataset folder not found: {days_dir}")
    day_files = {}
    for name in os.listdir(days_dir):
        day = _day_from_name(name)
        path = os.path.join(days_dir, name)
        if day is not None and name.lower().endswith(".jsonl") and os.path.isfile(path):
            day_files[day] = path
    if not day_files:
        raise FileNotFoundError(f"No day-XX.jsonl files found in {days_dir}")

    init_db(reset=False)
    conn = get_connection()
    try:
        sync_workspace_metadata(conn, data_dir=DATA_DIR)
        added = 0
        for day, path in sorted(day_files.items()):
            for record in _load_jsonl(path):
                if conn.execute("SELECT 1 FROM records WHERE id = ?", (record["id"],)).fetchone():
                    continue
                insert_record(conn, record, day)
                added += 1
        feedback_added = _import_feedback(conn)
        conn.commit()
        orgs = [row["org"] for row in conn.execute(
            "SELECT DISTINCT org FROM people WHERE org IS NOT NULL ORDER BY org"
        ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        days = [row["day"] for row in conn.execute(
            "SELECT DISTINCT day FROM records WHERE day IS NOT NULL ORDER BY day"
        ).fetchall()]
        return {"orgs": orgs, "added": added, "feedback_added": feedback_added,
                "total": total, "days": days, "files": len(day_files),
                "latest_day": max(day_files)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cutoff_for_day(day):
    # Every selected day is cumulative. Never remove the day boundary for hidden days.
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MAX(at) AS cutoff FROM records WHERE day <= ?", (day,)
        ).fetchone()
        return row["cutoff"] if row and row["cutoff"] else None
    finally:
        conn.close()


def _choose_workspace(orgs):
    if not orgs:
        raise RuntimeError("No workspace organization was found in dataset/data/people.json.")
    if len(orgs) == 1:
        return orgs[0]
    print("\nAvailable workspaces:")
    for index, org in enumerate(orgs, 1):
        print(f"  {index}. {org}")
    while True:
        value = input("Select workspace number: ").strip()
        try:
            selected = int(value)
            if 1 <= selected <= len(orgs):
                return orgs[selected - 1]
        except ValueError:
            pass
        print("Enter one of the listed numbers.")


def _choose_day(default_day):
    while True:
        value = input(f"Dataset day [1–15, default {default_day}]: ").strip()
        if not value:
            return default_day
        try:
            day = int(value)
            if 1 <= day <= 15:
                return day
        except ValueError:
            pass
        print("Enter a day from 1 to 15.")


def _show_result(result):
    if result.get("refused"):
        print(f"\nMemoFlow: {result['refused'].get('reason', 'Access denied.')}")
    elif result.get("clarify"):
        clarification = result["clarify"]
        print(f"\nMemoFlow: {clarification.get('question', 'Please clarify.')}")
        for option in clarification.get("options") or []:
            print(f"  - {option.get('text', '')}")
    elif result.get("answer"):
        answer = result["answer"]
        print(f"\nMemoFlow: {answer.get('text', 'No answer.')}")
        sources = answer.get("sources") or []
        if sources:
            print("Sources: " + ", ".join(sources))
    else:
        print("\nMemoFlow: I couldn't find a reliable answer in the authorized records.")
    usage = result.get("usage") or {}
    if usage:
        print(f"[{usage.get('ms', 0)} ms | {usage.get('input_tokens', 0)} in / "
              f"{usage.get('output_tokens', 0)} out tokens | "
              f"${usage.get('cost_usd', 0):.6f}]")
    print()


def _print_scope(day, cutoff):
    print(f"Scope: cumulative Days 1–{day}; hard day boundary enforced (timestamp cutoff: {cutoff or 'no records'}).")


def run_tui():
    print("\nMemoFlow — Workspace Memory Assistant")
    print("Starting local SQLite database and importing bundled dataset…")
    try:
        info = bootstrap_dataset()
    except Exception as exc:
        print(f"Dataset initialization failed: {exc}")
        return

    print(f"SQLite ready: {info['total']:,} records | {info['files']} day files | "
          f"{info['added']} newly imported | {info['feedback_added']} feedback rows imported")
    print("Available day files: " + (", ".join(map(str, info["days"])) or "none"))
    print("Security mode: workspace session; team-visible records only. "
          "Private/restricted records require verified employee identity and are blocked here.")

    try:
        org = _choose_workspace(info["orgs"])
        day = _choose_day(min(15, max(info["days"]) if info["days"] else 5))
    except (EOFError, KeyboardInterrupt):
        print("\nExited.")
        return

    person = "__workspace__:" + org
    cutoff = _cutoff_for_day(day)
    print(f"\nWorkspace: {org}")
    _print_scope(day, cutoff)
    print("Type a question and press Enter. Commands: /day N, /refresh, /help, /exit")
    print("Note: workspace chat is not employee authentication; private/restricted content stays inaccessible.\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExited.")
            break
        if not question:
            continue
        command = question.casefold()
        if command in {"/exit", "/quit"}:
            print("Goodbye.")
            break
        if command == "/help":
            print("Ask any question about accessible workspace records.")
            print("/day N   Change dataset scope (cumulative Days 1–N; later days are excluded)")
            print("/refresh Re-import newly added day/feedback files into SQLite")
            print("/exit   Quit MemoFlow\n")
            continue
        if command.startswith("/day "):
            try:
                new_day = int(question.split(maxsplit=1)[1])
                if not 1 <= new_day <= 15:
                    raise ValueError
                day = new_day
                cutoff = _cutoff_for_day(day)
                _print_scope(day, cutoff)
            except (ValueError, IndexError):
                print("Use /day followed by a number from 1 to 15.\n")
            continue
        if command == "/refresh":
            try:
                info = bootstrap_dataset()
                cutoff = _cutoff_for_day(day)
                print(f"Refreshed: {info['total']:,} records total; "
                      f"{info['added']} new records imported.")
                if org not in info["orgs"]:
                    print("Warning: selected workspace is no longer in the people directory.")
                _print_scope(day, cutoff)
            except Exception as exc:
                print(f"Refresh failed: {exc}")
            print()
            continue

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            result = answer_ask(person, now, question, dataset_cutoff=cutoff, dataset_day=day)
            _show_result(result)
        except Exception as exc:
            print(f"Request failed: {exc}\n")


if __name__ == "__main__":
    run_tui()
