# MemoFlow: Autonomous Meeting Brief & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It autonomously processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with strict privacy boundaries and zero hallucination.

## Architecture & Tech Stack

1. **Storage & Indexing (`db.py`):**
   - **SQLite**: Local, persistent database storing records, task histories, meeting schedules, feedback, and open promises.
   - **SQLite FTS5**: Full-text search engine indexing titles, bodies, authors, subjects, and channels for fast text retrieval.
2. **Metadata & Permission Filter (`filter.py`):**
   - **Org Boundaries**: Strictly isolates Kitepoint (`org_kp`) from external or competitor records (`org_bw`).
   - **Visibility Controls**: Enforces `team`, `private`, and `restricted` visibility rules.
   - **User Preferences & Forgets**: Filters out newsletters if requested and hides data that users requested to forget.
3. **Meeting Brief Engine (`brief_engine.py`):**
   - Detects decisions, blocked tasks, owner changes, date shifts, and completed tasks since the previous client meeting.
   - Tracks open promises and extracts pre-meeting questions.
   - Honors preferences (e.g., maximum change limits, prioritizing blockers).
4. **Question Answering Engine (`ask_engine.py`):**
   - Handles entity disambiguation, task status, due dates, ownership lookups, and personal reminders.
   - Enforces privacy refusal for unauthorized queries and asks clarifying questions for ambiguous requests.
5. **LLM Interface & Usage Tracking (`llm.py`):**
   - Connects to external LLM APIs (Gemini / OpenAI) when keys are configured, with deterministic fallback extraction.
   - Honest, accurate reporting of token usage (`input_tokens`, `output_tokens`, `cost_usd`, `ms`).

## CLI Interface

```bash
# Ingest day N records
python MemoFlow/main.py ingest --day 1

# Generate briefs for meetings of person P on date D
python MemoFlow/main.py brief --person p02 --date 2026-11-03

# Answer questions asked by person P at UTC timestamp ISO
python MemoFlow/main.py ask --person p02 --at 2026-11-02T18:00:00Z --ask "Who handles billing for NB?"

# Forget something requested by person P
python MemoFlow/main.py forget --person p02 --what "my Dubai travel"
```

