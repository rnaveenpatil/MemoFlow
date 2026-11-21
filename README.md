# MemoFlow: Autonomous Meeting Brief & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with privacy boundaries and source citations.

## Quick start: chat-first mode

Run from the MemoFlow project directory:

```bash
python main.py
```

MemoFlow opens as a normal chat assistant:

1. Enter your workspace name once. You do not need to know or type an internal person ID. This identity step is required so MemoFlow can enforce private and restricted visibility correctly.
2. Select a JSONL day file. MemoFlow detects the day from its filename and imports the available history from Day 1 through that day into its persistent SQLite database. It never scans or imports future days.
3. Start typing natural-language questions directly. Mention people by name; MemoFlow asks the language model to resolve names against `people.json`, validates the returned IDs against that directory, and uses the resolved identity for retrieval.
4. Use `/file` to select and ingest another day file, `/whoami` to see the active workspace identity, or `/exit` to quit.

If two people have the same name, MemoFlow asks you to disambiguate instead of guessing. Internal IDs are used by the application and database, not required from the user.

Keep earlier day files together in the selected file's folder, or place them under `data/days/`. Filenames must contain a day marker such as `day-01.jsonl`, `day-2.jsonl`, or `Day 3.jsonl`. Missing earlier days cause a clear error rather than silently creating incomplete history. Re-importing an existing record ID is skipped to avoid duplicate history.

**Data and privacy:** selected dataset records are stored in the local SQLite database. The database is shared workspace storage, not a separate copy per person. Every query is filtered by organization, visibility (`team`, `private`, `restricted`), as-of time, and forget rules before evidence is sent to the LLM. Mentioning another person's name never grants access to their private records.


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
