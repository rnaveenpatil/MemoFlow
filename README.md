# MemoFlow: Autonomous Meeting Brief & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with privacy boundaries and source citations.

## Quick start: interactive mode

Run from the MemoFlow project directory:

```bash
python main.py
```

The interactive terminal UI lets you:
1. Select a day file such as `day-01.jsonl` or `day-03.jsonl`.
2. MemoFlow detects the day from the filename; no manual day number is required.
3. Selecting Day N imports the available files for Days 1 through N in chronological order. It never reads later-day files. Missing earlier files cause a clear error rather than silently creating incomplete history.
4. Previously ingested days remain in the database. Re-importing the same records does not create duplicate records.
5. Select your person ID and type questions; answers include source record IDs.

Keep the earlier day files together in the selected file's folder, or place them under `data/days/`. Filenames must contain a day marker such as `day-01.jsonl`, `day-2.jsonl`, or `Day 3.jsonl`. The TUI will not guess a day from file selection order.

Commands inside question mode:
- `/person` — switch the person asking
- `/file` — return to the file selection menu
- `/exit` — quit question mode

You can also launch it explicitly with `python main.py tui`.

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
