# MemoFlow: Workspace Memory & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with privacy boundaries and source citations.

## Quick start: MemoFlow chat UI

Run:

```bash
python main.py
```

The desktop-style Tkinter interface includes a **MEMOFLOW** banner, a dataset-day selector (1–15), JSONL file picker, workspace selector, scrollable chat transcript, and a message composer at the bottom. Press **Ctrl+Enter** or click **Send** to ask a question.

### Dataset-day behavior

- **Day 1–5:** imports cumulative source files Day 1 through the selected day. The query engine applies the selected day's latest record timestamp as a hard upper bound, so later records cannot be used to answer.
- **Day 6–15:** imports and searches every available day file in the selected dataset folder. It does not guess that hidden days exist; if the supplied files do not contain the answer, MemoFlow says the evidence is unavailable.
- Re-imports are idempotent. Records, people, clients, feedback, task history, and forget rules are stored in SQLite. Original JSONL files are not modified.
- The selected dataset day is separate from the date in a question. Natural-language dates are resolved by the LLM; Python applies the SQL time boundary.

### Privacy and identity

The UI does not pretend that mentioning an employee name authenticates the speaker. Choose a workspace organization before chatting. In identity-free mode MemoFlow can read **team-visible** records only; private and restricted records are denied. Supporting private/restricted access requires a verified member login, which this UI does not claim to provide. Organizations are isolated before retrieval and before evidence reaches the LLM.

### Chat behavior

Ask about people, clients, tasks, meetings, decisions, and changes in natural language. The LLM interprets the request and synthesizes only retrieved records. Every answer must cite source record IDs. Explicit “remember” or “correct” instructions are saved as clearly labelled user-provided notes; explicit forget requests create retrieval-suppression rules. Forget is not represented as physical deletion of the original source file.


## Architecture & Tech Stack

1. **Storage & Indexing (`db.py`):**
   - **SQLite**: Local, persistent database storing records, task histories, meeting schedules, feedback, and open promises.
   - **SQLite FTS5**: Full-text search engine indexing titles, bodies, authors, subjects, and channels for fast retrieval.
2. **Metadata & Permission Filter (`filter.py`):**
   - Enforces organization and visibility boundaries, plus forget requests.
3. **Meeting Brief Engine (`brief_engine.py`):**
   - Generates meeting briefs from task changes, decisions, blockers, and open promises.
4. **Question Answering Engine (`ask_engine.py`):**
   - Uses model-assisted interpretation and dataset-grounded evidence retrieval, with source ID validation.
5. **LLM Interface (`llm.py`):**
   - Configure an OpenAI-compatible provider using the environment variables below.

## LLM configuration

Create a `.env` file in the project directory:

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL_ID=your-model-id
LLM_API_KEY=your-api-key
```

## CLI commands

```bash
# Ingest a bundled dataset day
python main.py ingest --day 1

# Generate a person's daily brief
python main.py brief --person p02 --date 2026-11-03

# Ask a question at an explicit UTC timestamp
python main.py ask --person p02 --at 2026-11-02T18:00:00Z --ask "Who handles billing for NB?"

# Store a forget request
python main.py forget --person p02 --what "my Dubai travel"
```
