"""MemoFlow desktop-style terminal workspace UI.

Tkinter is part of Python's standard library. The UI provides a day selector,
workspace selector, JSONL file picker, scrollable chat transcript and composer.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from MemoFlow.ask_engine import answer_ask
from MemoFlow.config import DATA_DIR
from MemoFlow.db import get_connection, init_db, insert_record, sync_workspace_metadata

_DAY_RE = re.compile(r"(?:^|[^a-z0-9])day[-_ ]?0*(\d+)(?:[^0-9]|$)", re.I)


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


def _day_from_name(path):
    match = _DAY_RE.search(os.path.basename(path))
    return int(match.group(1)) if match else None


def _find_data_root(selected_path):
    start = os.path.dirname(os.path.abspath(selected_path))
    current = start
    for _ in range(8):
        if os.path.isfile(os.path.join(current, "people.json")):
            return current
        if os.path.isdir(os.path.join(current, "days")) and os.path.isfile(os.path.join(current, "people.json")):
            return os.path.join(current, "data") if os.path.isfile(os.path.join(current, "data", "people.json")) else current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return DATA_DIR


def _discover_day_files(selected_path, data_root):
    dirs = {
        os.path.dirname(os.path.abspath(selected_path)),
        os.path.join(data_root, "days"),
        data_root,
    }
    files = {}
    for folder in dirs:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            day = _day_from_name(name)
            if day and name.lower().endswith(".jsonl") and os.path.isfile(path):
                files.setdefault(day, path)
    # If the selected file has an unrecognized name, it is still a valid input;
    # its records are included in the all-data mode.
    if not _day_from_name(selected_path):
        files.setdefault(0, os.path.abspath(selected_path))
    return files


def _import_workspace(selected_path, selected_day):
    if not selected_path or not os.path.isfile(selected_path):
        raise ValueError("Choose a valid JSONL dataset file first.")
    if not 1 <= selected_day <= 15:
        raise ValueError("Select a dataset day between 1 and 15.")

    data_root = _find_data_root(selected_path)
    files = _discover_day_files(selected_path, data_root)
    if selected_day <= 5:
        # For Days 1–5, cumulative import is strictly bounded to physical day files 1..N.
        wanted = {day: path for day, path in files.items() if 1 <= day <= selected_day}
        if selected_day not in wanted:
            wanted[selected_day] = os.path.abspath(selected_path)
        missing = [day for day in range(1, selected_day + 1) if day not in wanted]
        if missing:
            raise ValueError("Missing required cumulative file(s): " + ", ".join(f"Day {d}" for d in missing))
        cutoff_mode = "cumulative"
    else:
        # Days 6–15 mean search every available dataset file, not a guessed subset.
        wanted = {day: path for day, path in files.items()}
        if not wanted:
            wanted = {selected_day: os.path.abspath(selected_path)}
        cutoff_mode = "all"

    init_db(reset=False)
    conn = get_connection()
    try:
        sync_workspace_metadata(conn, data_dir=data_root)
        added = 0
        imported_by_day = {}
        for day, path in sorted(wanted.items()):
            day_added = 0
            for record in _load_jsonl(path):
                # Preserve source timestamps; day is the source-file day used for cutoff.
                existing = conn.execute("SELECT 1 FROM records WHERE id = ?", (record["id"],)).fetchone()
                if existing:
                    continue
                insert_record(conn, record, day if day > 0 else selected_day)
                day_added += 1
            imported_by_day[day] = day_added
            added += day_added

        # Import applicable feedback idempotently. Feedback never becomes evidence text.
        feedback_count = 0
        feedback_dir = os.path.join(data_root, "feedback")
        if os.path.isdir(feedback_dir):
            for name in os.listdir(feedback_dir):
                match = re.search(r"day[-_ ]?0*(\d+)", name, re.I)
                if not match or not name.lower().endswith(".jsonl"):
                    continue
                feedback_day = int(match.group(1))
                if cutoff_mode == "cumulative" and feedback_day > selected_day:
                    continue
                path = os.path.join(feedback_dir, name)
                with open(path, "r", encoding="utf-8-sig") as feedback_stream:
                    feedback_rows = [json.loads(line) for line in feedback_stream if line.strip()]
                for fb in feedback_rows:
                    vals = (fb.get("day"), fb.get("person"), fb.get("type"), fb.get("words"),
                            fb.get("meeting"), fb.get("topic"), fb.get("verdict"))
                    exists = conn.execute(
                        """SELECT 1 FROM feedback WHERE day IS ? AND person IS ? AND type IS ?
                           AND words IS ? AND meeting IS ? AND topic IS ? AND verdict IS ? LIMIT 1""",
                        vals
                    ).fetchone()
                    if exists:
                        continue
                    conn.execute(
                        """INSERT INTO feedback(day,person,type,words,meeting,topic,verdict)
                           VALUES(?,?,?,?,?,?,?)""", vals
                    )
                    if fb.get("type") == "forget" and fb.get("words"):
                        conn.execute("INSERT INTO forgets(person,what) VALUES(?,?)",
                                     (fb.get("person") or "*", fb["words"]))
                    feedback_count += 1
        conn.commit()
        orgs = [row["org"] for row in conn.execute(
            "SELECT DISTINCT org FROM people WHERE org IS NOT NULL ORDER BY org"
        ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        max_day = conn.execute("SELECT MAX(day) FROM records").fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if cutoff_mode == "cumulative":
        # Use the latest timestamp in the selected source day as the hard query ceiling.
        conn = get_connection()
        try:
            row = conn.execute("SELECT MAX(at) AS at FROM records WHERE day <= ?", (selected_day,)).fetchone()
            cutoff = row["at"] if row and row["at"] else None
        finally:
            conn.close()
    else:
        cutoff = None

    return {
        "data_root": data_root, "orgs": orgs, "added": added,
        "feedback": feedback_count, "total": total, "max_day": max_day,
        "cutoff": cutoff, "mode": cutoff_mode, "files": len(wanted),
        "selected_day": selected_day
    }


class MemoFlowApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MemoFlow — Workspace Assistant")
        self.root.geometry("1000x720")
        self.root.minsize(760, 560)
        self.selected_file = ""
        self.active_org = ""
        self.dataset_cutoff = None
        self.workspace_person = ""
        self.busy = False

        self._build_ui()
        self._set_status("Select a dataset file, choose a day, then load workspace.")

    def _build_ui(self):
        self.root.configure(bg="#101827")
        header = tk.Frame(self.root, bg="#101827", padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="MEMOFLOW", bg="#101827", fg="#f4f7fb",
                 font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(header, text="WORKSPACE MEMORY  •  CONTEXT-AWARE AI ASSISTANT",
                 bg="#101827", fg="#8fa3bd", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(3, 0))

        controls = tk.LabelFrame(self.root, text="  DATASET CONTROL  ",
                                 bg="#182437", fg="#dce6f3", padx=14, pady=12,
                                 font=("Segoe UI", 9, "bold"), bd=1, relief="solid")
        controls.pack(fill="x", padx=18, pady=(0, 12))

        row = tk.Frame(controls, bg="#182437")
        row.pack(fill="x")
        tk.Label(row, text="Dataset day N", bg="#182437", fg="#dce6f3",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.day_var = tk.IntVar(value=5)
        self.day_spin = tk.Spinbox(row, from_=1, to=15, width=5, textvariable=self.day_var,
                                   font=("Segoe UI", 11), justify="center")
        self.day_spin.pack(side="left", padx=(10, 18))
        self.pick_btn = tk.Button(row, text="Select JSONL file", command=self._pick_file,
                                  bg="#263b56", fg="white", activebackground="#345477",
                                  relief="flat", padx=14, pady=7, cursor="hand2")
        self.pick_btn.pack(side="left")
        self.load_btn = tk.Button(row, text="Load workspace", command=self._load,
                                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                                  relief="flat", padx=16, pady=7, cursor="hand2")
        self.load_btn.pack(side="left", padx=8)
        self.org_var = tk.StringVar()
        self.org_box = ttk.Combobox(row, textvariable=self.org_var, state="readonly", width=24)
        self.org_box.bind("<<ComboboxSelected>>", self._org_changed)
        self.org_box.pack(side="right")
        tk.Label(row, text="Workspace", bg="#182437", fg="#dce6f3").pack(side="right", padx=8)

        self.file_label = tk.Label(controls, text="No dataset file selected",
                                   bg="#182437", fg="#8fa3bd", anchor="w")
        self.file_label.pack(fill="x", pady=(8, 0))
        self.status = tk.Label(self.root, text="", bg="#101827", fg="#93c5fd",
                               anchor="w", padx=22, pady=4, font=("Segoe UI", 9))
        self.status.pack(fill="x")

        chat_frame = tk.Frame(self.root, bg="#172235", padx=12, pady=12)
        chat_frame.pack(fill="both", expand=True, padx=18, pady=(4, 12))
        top = tk.Frame(chat_frame, bg="#172235")
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="CHAT", bg="#172235", fg="#e5edf7",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(top, text="Ask naturally • source IDs are shown with answers",
                 bg="#172235", fg="#91a4bc", font=("Segoe UI", 9)).pack(side="right")

        transcript_frame = tk.Frame(chat_frame, bg="#0e1726")
        transcript_frame.pack(fill="both", expand=True)
        self.chat = tk.Text(transcript_frame, wrap="word", state="disabled",
                            bg="#0e1726", fg="#dbe6f3", insertbackground="white",
                            relief="flat", padx=16, pady=14, font=("Segoe UI", 10),
                            spacing1=3, spacing3=7)
        scrollbar = ttk.Scrollbar(transcript_frame, command=self.chat.yview)
        self.chat.configure(yscrollcommand=scrollbar.set)
        self.chat.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.chat.tag_configure("assistant", foreground="#93c5fd", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("user", foreground="#86efac", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("muted", foreground="#8fa3bd", font=("Segoe UI", 9))

        composer = tk.Frame(self.root, bg="#101827", padx=18, pady=(0, 18))
        composer.pack(fill="x")
        self.question = tk.Text(composer, height=3, wrap="word", bg="#1c2b40",
                                fg="#f3f6fb", insertbackground="white", relief="flat",
                                padx=12, pady=10, font=("Segoe UI", 10))
        self.question.pack(side="left", fill="x", expand=True)
        self.question.bind("<Control-Return>", self._send_event)
        self.send_btn = tk.Button(composer, text="Send  ➤", command=self._send,
                                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                                  relief="flat", padx=20, pady=12, cursor="hand2")
        self.send_btn.pack(side="left", padx=(10, 0))
        self.question.insert("1.0", "Ask MemoFlow about a person, client, task, meeting, or decision…")
        self.question.bind("<FocusIn>", self._clear_placeholder)

    def _clear_placeholder(self, _event=None):
        if self.question.get("1.0", "end-1c").startswith("Ask MemoFlow about"):
            self.question.delete("1.0", "end")

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select any MemoFlow dataset JSONL file",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")]
        )
        if path:
            self.selected_file = path
            self.file_label.configure(text=path, fg="#dce6f3")
            day = _day_from_name(path)
            if day and 1 <= day <= 15:
                self.day_var.set(day)

    def _set_status(self, text):
        self.status.configure(text=text)

    def _append(self, speaker, message, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", speaker + "\n", tag)
        self.chat.insert("end", message.strip() + "\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _load(self):
        if not self.selected_file:
            messagebox.showwarning("Dataset required", "Select a JSONL dataset file first.")
            return
        try:
            day = int(self.day_var.get())
            result = _import_workspace(self.selected_file, day)
            orgs = result["orgs"]
            if not orgs:
                raise ValueError("No workspace organizations found in people.json.")
            self.org_box["values"] = orgs
            self.org_var.set(orgs[0] if len(orgs) == 1 else "")
            self.active_org = orgs[0] if len(orgs) == 1 else ""
            self.dataset_cutoff = result["cutoff"]
            self.workspace_person = "__workspace__:" + self.active_org if self.active_org else ""
            mode = ("Days 1–" + str(day) + " only" if result["mode"] == "cumulative"
                    else "ALL available dataset files (Days 1–15 mode)")
            self._set_status(
                f"Loaded {result['files']} file(s) • +{result['added']} records • "
                f"{result['total']} total in SQLite • {mode}"
            )
            self._append("MemoFlow", f"Workspace loaded. {mode}. "
                         "Privacy: identity-free mode exposes team-visible records only; "
                         "private/restricted records are denied. Ask your question below.", "assistant")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            self._set_status("Dataset load failed. Fix the issue and try again.")

    def _org_changed(self, _event=None):
        self.active_org = self.org_var.get().strip()
        self.workspace_person = "__workspace__:" + self.active_org if self.active_org else ""

    def _send_event(self, _event=None):
        self._send()
        return "break"

    def _send(self):
        question = self.question.get("1.0", "end-1c").strip()
        if not question or question.startswith("Ask MemoFlow about"):
            return
        if not self.workspace_person:
            messagebox.showwarning("Workspace required", "Load a dataset and choose a workspace first.")
            return
        if self.busy:
            return
        self.question.delete("1.0", "end")
        self._append("You", question, "user")
        self.busy = True
        self.send_btn.configure(state="disabled", text="Thinking…")
        self._set_status("Searching authorized SQLite evidence and consulting the language model…")

        def worker():
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                result = answer_ask(
                    self.workspace_person, now, question,
                    dataset_cutoff=self.dataset_cutoff
                )
                self.root.after(0, lambda: self._show_result(result))
            except Exception as exc:
                self.root.after(0, lambda: self._show_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, result):
        self.busy = False
        self.send_btn.configure(state="normal", text="Send  ➤")
        self._set_status("Ready")
        if result.get("refused"):
            self._append("MemoFlow", result["refused"].get("reason", "Not authorized."), "assistant")
        elif result.get("clarify"):
            clarify = result["clarify"]
            self._append("MemoFlow", clarify.get("question", "Please clarify.") +
                         ("\n" + "\n".join("- " + x.get("text", "") for x in clarify.get("options", []))
                          if clarify.get("options") else ""), "assistant")
        elif result.get("answer"):
            answer = result["answer"]
            sources = answer.get("sources") or []
            self._append("MemoFlow", answer.get("text", "No answer.") +
                         ("\n\nSources: " + ", ".join(sources) if sources else ""), "assistant")
        else:
            self._append("MemoFlow", "I couldn't find a reliable answer in the authorized records.", "assistant")

    def _show_error(self, error):
        self.busy = False
        self.send_btn.configure(state="normal", text="Send  ➤")
        self._set_status("Request failed")
        self._append("MemoFlow", "Error: " + error, "assistant")


def run_tui():
    init_db(reset=False)
    root = tk.Tk()
    MemoFlowApp(root)
    root.mainloop()
