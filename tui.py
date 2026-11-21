"""MemoFlow desktop workspace assistant.

The bundled dataset is discovered and ingested into SQLite automatically.
Users select only the dataset day and workspace; they never browse for files.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
import tkinter as tk
from tkinter import messagebox, ttk

from MemoFlow.ask_engine import answer_ask
from MemoFlow.config import DATA_DIR
from MemoFlow.db import get_connection, init_db, insert_record, sync_workspace_metadata

_DAY_RE = re.compile(r"day[-_ ]?0*(\d+)", re.I)
_BG = "#0b1220"
_PANEL = "#111c2e"
_PANEL_ALT = "#17243a"
_INPUT = "#1b2a41"
_TEXT = "#e7edf6"
_MUTED = "#91a2bb"
_BLUE = "#3b82f6"
_GREEN = "#34d399"


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
        path = os.path.join(feedback_dir, name)
        with open(path, "r", encoding="utf-8-sig") as stream:
            feedback_rows = [json.loads(line) for line in stream if line.strip()]
        for fb in feedback_rows:
            if not isinstance(fb, dict):
                continue
            values = (fb.get("day"), fb.get("person"), fb.get("type"), fb.get("words"),
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
            if fb.get("type") == "forget" and fb.get("words"):
                forget_exists = conn.execute(
                    "SELECT 1 FROM forgets WHERE person = ? AND what = ? LIMIT 1",
                    (fb.get("person") or "*", fb["words"])
                ).fetchone()
                if not forget_exists:
                    conn.execute("INSERT INTO forgets(person,what) VALUES(?,?)",
                                 (fb.get("person") or "*", fb["words"]))
            added += 1
    return added


def bootstrap_dataset():
    """Ingest every bundled day file once; SQLite is the runtime data source."""
    days_dir = os.path.join(DATA_DIR, "days")
    if not os.path.isdir(days_dir):
        raise FileNotFoundError(
            f"Dataset folder not found: {days_dir}. Keep the supplied dataset/data folder in the project."
        )

    day_files = {}
    for name in os.listdir(days_dir):
        day = _day_from_name(name)
        path = os.path.join(days_dir, name)
        if day is not None and name.lower().endswith(".jsonl") and os.path.isfile(path):
            day_files[day] = path
    if not day_files:
        raise FileNotFoundError(f"No day-XX.jsonl files found in {days_dir}.")

    init_db(reset=False)
    conn = get_connection()
    try:
        sync_workspace_metadata(conn, data_dir=DATA_DIR)
        added = 0
        for day, path in sorted(day_files.items()):
            for record in _load_jsonl(path):
                exists = conn.execute("SELECT 1 FROM records WHERE id = ?", (record["id"],)).fetchone()
                if exists:
                    continue
                insert_record(conn, record, day)
                added += 1

        feedback_added = _import_feedback(conn)
        conn.commit()
        orgs = [row["org"] for row in conn.execute(
            "SELECT DISTINCT org FROM people WHERE org IS NOT NULL ORDER BY org"
        ).fetchall()]
        if not orgs:
            orgs = [row["org"] for row in conn.execute(
                "SELECT DISTINCT org FROM records WHERE org IS NOT NULL ORDER BY org"
            ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        db_days = [row["day"] for row in conn.execute(
            "SELECT DISTINCT day FROM records WHERE day IS NOT NULL ORDER BY day"
        ).fetchall()]
        return {
            "orgs": orgs, "added": added, "feedback_added": feedback_added,
            "total": total, "days": db_days, "files": len(day_files),
            "latest_day": max(day_files)
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cutoff_for_day(day):
    """Days 1–5 are cumulative and time-bounded; Day 6+ means all DB data."""
    if day > 5:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MAX(at) AS cutoff FROM records WHERE day <= ?", (day,)
        ).fetchone()
        return row["cutoff"] if row and row["cutoff"] else None
    finally:
        conn.close()


class MemoFlowApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MemoFlow | Workspace Assistant")
        self.root.geometry("1080x760")
        self.root.minsize(780, 600)
        self.active_org = ""
        self.workspace_person = ""
        self.dataset_cutoff = None
        self.busy = False
        self.dataset_info = None

        self._build_ui()
        self._bootstrap()

    def _build_ui(self):
        self.root.configure(bg=_BG)

        header = tk.Frame(self.root, bg=_BG, padx=26, pady=20)
        header.pack(fill="x")
        title_row = tk.Frame(header, bg=_BG)
        title_row.pack(fill="x")
        tk.Label(title_row, text="MEMOFLOW", bg=_BG, fg="#f8fafc",
                 font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(title_row, text="WORKSPACE MEMORY  /  AI ASSISTANT",
                 bg=_BG, fg=_MUTED, font=("Segoe UI", 9, "bold")).pack(side="left", padx=16, pady=(9, 0))
        tk.Label(header, text="Ask questions across your team's messages, meetings, tasks and decisions.",
                 bg=_BG, fg="#aebdd0", font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        controls = tk.Frame(self.root, bg=_PANEL, padx=18, pady=14,
                            highlightthickness=1, highlightbackground="#26364d")
        controls.pack(fill="x", padx=22, pady=(0, 10))
        left = tk.Frame(controls, bg=_PANEL)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="DATASET DAY", bg=_PANEL, fg=_MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        day_row = tk.Frame(left, bg=_PANEL)
        day_row.pack(anchor="w", pady=(5, 0))
        self.day_var = tk.IntVar(value=5)
        self.day_spin = tk.Spinbox(day_row, from_=1, to=15, width=4,
                                   textvariable=self.day_var, font=("Segoe UI", 11),
                                   justify="center", relief="flat", bg=_INPUT, fg=_TEXT,
                                   buttonbackground=_PANEL_ALT, insertbackground=_TEXT)
        self.day_spin.pack(side="left", ipady=5)
        self.apply_btn = tk.Button(day_row, text="Apply day", command=self._apply_day,
                                   bg=_BLUE, fg="white", activebackground="#2563eb",
                                   activeforeground="white", relief="flat", padx=14,
                                   pady=7, cursor="hand2", font=("Segoe UI", 9, "bold"))
        self.apply_btn.pack(side="left", padx=(8, 0))
        self.reload_btn = tk.Button(day_row, text="↻ Refresh database",
                                    command=self._refresh_dataset, bg=_PANEL_ALT,
                                    fg=_TEXT, activebackground="#263b56",
                                    activeforeground="white", relief="flat",
                                    padx=12, pady=7, cursor="hand2",
                                    font=("Segoe UI", 9))
        self.reload_btn.pack(side="left", padx=(8, 0))

        right = tk.Frame(controls, bg=_PANEL)
        right.pack(side="right", anchor="e")
        tk.Label(right, text="WORKSPACE", bg=_PANEL, fg=_MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="e")
        self.org_var = tk.StringVar()
        self.org_box = ttk.Combobox(right, textvariable=self.org_var,
                                    state="readonly", width=25)
        self.org_box.bind("<<ComboboxSelected>>", self._org_changed)
        self.org_box.pack(anchor="e", pady=(5, 0), ipady=4)

        self.status = tk.Label(self.root, text="Connecting to local workspace database…",
                               bg=_BG, fg="#93c5fd", anchor="w",
                               padx=25, pady=5, font=("Segoe UI", 9))
        self.status.pack(fill="x")

        chat_shell = tk.Frame(self.root, bg=_PANEL, padx=1, pady=1)
        chat_shell.pack(fill="both", expand=True, padx=22, pady=(5, 12))
        chat = tk.Frame(chat_shell, bg=_PANEL, padx=18, pady=14)
        chat.pack(fill="both", expand=True)

        chat_header = tk.Frame(chat, bg=_PANEL)
        chat_header.pack(fill="x", pady=(0, 12))
        tk.Label(chat_header, text="CONVERSATION", bg=_PANEL, fg=_TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(chat_header, text="Grounded answers  •  Source IDs included",
                 bg=_PANEL, fg=_MUTED, font=("Segoe UI", 9)).pack(side="right")

        transcript = tk.Frame(chat, bg=_BG)
        transcript.pack(fill="both", expand=True)
        self.chat = tk.Text(transcript, wrap="word", state="disabled",
                            bg=_BG, fg=_TEXT, insertbackground="white",
                            relief="flat", padx=18, pady=16,
                            font=("Segoe UI", 10), spacing1=4, spacing3=9,
                            selectbackground="#29466c")
        scroll = ttk.Scrollbar(transcript, command=self.chat.yview)
        self.chat.configure(yscrollcommand=scroll.set)
        self.chat.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.chat.tag_configure("assistant", foreground="#93c5fd",
                                font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("user", foreground=_GREEN,
                                font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("muted", foreground=_MUTED,
                                font=("Segoe UI", 9))
        self.chat.tag_configure("error", foreground="#fca5a5")

        composer = tk.Frame(self.root, bg=_BG, padx=22, pady=0)
        composer.pack(fill="x", pady=(0, 18))
        input_shell = tk.Frame(composer, bg=_INPUT, padx=1, pady=1)
        input_shell.pack(side="left", fill="x", expand=True)
        self.question = tk.Text(input_shell, height=3, wrap="word",
                                bg=_INPUT, fg=_TEXT, insertbackground="white",
                                relief="flat", padx=13, pady=11,
                                font=("Segoe UI", 10), undo=True)
        self.question.pack(fill="both", expand=True)
        self.question.bind("<Control-Return>", self._send_event)
        self.question.bind("<FocusIn>", self._clear_placeholder)
        self.send_btn = tk.Button(composer, text="Send  ➤", command=self._send,
                                  bg=_BLUE, fg="white", activebackground="#2563eb",
                                  activeforeground="white", relief="flat",
                                  padx=22, pady=13, cursor="hand2",
                                  font=("Segoe UI", 10, "bold"))
        self.send_btn.pack(side="left", padx=(10, 0))
        self.question.insert("1.0", "Ask about a person, client, task, meeting, decision…")
        self._placeholder = True
        tk.Label(self.root, text="Enter a question • Ctrl + Enter to send",
                 bg=_BG, fg="#71839c", font=("Segoe UI", 8)).pack(anchor="e", padx=26, pady=(0, 8))

    def _bootstrap(self):
        try:
            self.dataset_info = bootstrap_dataset()
            days = self.dataset_info["days"]
            default_day = min(15, max(days) if days else 5)
            self.day_var.set(default_day)
            orgs = self.dataset_info["orgs"]
            self.org_box["values"] = orgs
            if len(orgs) == 1:
                self.org_var.set(orgs[0])
                self._org_changed()
            elif orgs:
                self.org_var.set("")
                self._append("MemoFlow", "Dataset is ready. Select a workspace to begin.", "assistant")
            self._apply_day(show_message=False)
            self._set_status(
                f"SQLite ready • {self.dataset_info['total']:,} records • "
                f"{self.dataset_info['files']} dataset files • {self.dataset_info['added']} newly imported"
            )
            if not orgs:
                self._append("MemoFlow", "The database has records but no workspace organization metadata. Check people.json.", "error")
            elif len(orgs) == 1:
                self._append(
                    "MemoFlow",
                    "Your workspace database is ready. No file selection is needed. "
                    "Choose a dataset day, then ask your question. I will use only records "
                    "allowed by that day and the workspace's access rules.",
                    "assistant"
                )
        except Exception as exc:
            self._set_status("Dataset initialization failed")
            self._append("MemoFlow", str(exc), "error")

    def _set_status(self, value):
        self.status.configure(text=value)

    def _append(self, speaker, message, tag=""):
        self.chat.configure(state="normal")
        self.chat.insert("end", speaker + "\n", tag)
        self.chat.insert("end", str(message).strip() + "\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _clear_placeholder(self, _event=None):
        if self._placeholder:
            self.question.delete("1.0", "end")
            self._placeholder = False

    def _refresh_dataset(self):
        if self.busy:
            return
        try:
            info = bootstrap_dataset()
            self.dataset_info = info
            current = self.active_org
            orgs = info["orgs"]
            self.org_box["values"] = orgs
            if current in orgs:
                self.org_var.set(current)
            elif len(orgs) == 1:
                self.org_var.set(orgs[0])
            else:
                self.org_var.set("")
            self._org_changed()
            self._apply_day(show_message=False)
            self._set_status(
                f"Database refreshed • {info['total']:,} records • "
                f"{info['added']} new records imported"
            )
        except Exception as exc:
            self._set_status("Database refresh failed")
            messagebox.showerror("Refresh failed", str(exc))

    def _apply_day(self, show_message=True):
        try:
            day = int(self.day_var.get())
            if not 1 <= day <= 15:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("Invalid day", "Choose a day from 1 to 15.")
            return
        self.dataset_cutoff = _cutoff_for_day(day)
        if day <= 5:
            if not self.dataset_cutoff:
                self._set_status(f"No records are available through Day {day}.")
            else:
                self._set_status(f"Day {day} active • cumulative Days 1–{day} • later records blocked")
        else:
            self._set_status(f"Day {day} active • searching all records currently available in SQLite")
        if show_message:
            mode = f"cumulative Days 1–{day}" if day <= 5 else "all available SQLite records"
            self._append("MemoFlow", f"Dataset scope changed to {mode}.", "muted")

    def _org_changed(self, _event=None):
        self.active_org = self.org_var.get().strip()
        self.workspace_person = "__workspace__:" + self.active_org if self.active_org else ""

    def _send_event(self, _event=None):
        self._send()
        return "break"

    def _send(self):
        question = self.question.get("1.0", "end-1c").strip()
        if self._placeholder or not question:
            return
        if not self.workspace_person:
            messagebox.showwarning("Workspace required", "Select a workspace before asking a question.")
            return
        if self.busy:
            return

        self.question.delete("1.0", "end")
        self._append("You", question, "user")
        self.busy = True
        self.send_btn.configure(state="disabled", text="Thinking…")
        self.apply_btn.configure(state="disabled")
        self.reload_btn.configure(state="disabled")
        self._set_status("Searching SQLite evidence and consulting the language model…")
        person = self.workspace_person
        cutoff = self.dataset_cutoff

        def worker():
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                result = answer_ask(person, now, question, dataset_cutoff=cutoff)
                self.root.after(0, lambda: self._show_result(result))
            except Exception as exc:
                try:
                    self.root.after(0, lambda error=str(exc): self._show_error(error))
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _request_finished(self):
        self.busy = False
        self.send_btn.configure(state="normal", text="Send  ➤")
        self.apply_btn.configure(state="normal")
        self.reload_btn.configure(state="normal")
        self._set_status("Ready")

    def _show_result(self, result):
        self._request_finished()
        if result.get("refused"):
            self._append("MemoFlow", result["refused"].get("reason", "Not authorized."), "error")
        elif result.get("clarify"):
            clarify = result["clarify"]
            options = clarify.get("options") or []
            extra = "\n" + "\n".join("- " + item.get("text", "") for item in options)
            self._append("MemoFlow", clarify.get("question", "Please clarify.") + extra, "assistant")
        elif result.get("answer"):
            answer = result["answer"]
            sources = answer.get("sources") or []
            text = answer.get("text", "No answer.")
            if sources:
                text += "\n\nSources: " + ", ".join(sources)
            self._append("MemoFlow", text, "assistant")
        else:
            self._append("MemoFlow", "I couldn't find a reliable answer in the authorized records.", "assistant")

    def _show_error(self, error):
        self._request_finished()
        self._append("MemoFlow", "Request failed: " + error, "error")


def run_tui():
    init_db(reset=False)
    root = tk.Tk()
    MemoFlowApp(root)
    root.mainloop()
