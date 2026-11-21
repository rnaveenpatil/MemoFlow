# MemoFlow: Workspace Memory & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with privacy boundaries and source citations.

## Quick start: terminal chat

Run:

```bash
python main.py
```

The terminal assistant automatically discovers the bundled dataset, imports all available day files into SQLite, and opens an interactive chat. No file picker or manual ingestion is required. Select a workspace and dataset day when prompted, then type questions directly at `You:`. Keep chatting until `/exit`.

Commands inside chat: `/day N` changes the dataset scope, `/refresh` imports newly added files, and `/help` lists commands.

### Dataset-day behavior

- On startup, **all day files present in the bundled dataset folder are ingested into SQLite**. Existing record IDs are not imported twice.
- **Day 1–15:** the query engine uses cumulative records from Day 1 through the selected day, inclusive. Both the day column and the selected day's latest timestamp are enforced; later-day records cannot influence answers even when already ingested. Missing hidden-day files are not fabricated. Use `/refresh` after adding files.
- Records, people, clients, feedback, task history, and forget rules are stored in SQLite. Original JSONL files are not modified.
- Feedback rows are ingested, but person-specific preferences and correction/verdict feedback are not yet applied to question-answering. The current workspace-only session cannot safely decide which employee's preferences should govern a response.
- The selected dataset day is separate from dates mentioned in questions. The LLM interprets natural-language date intent; Python enforces the SQL time boundary.

### Privacy and identity

The terminal session does not authenticate an individual employee. It can read **team-visible** records only; private and restricted records are denied. Do not treat selecting a workspace or mentioning an employee name as identity verification. Private/restricted access requires a verified member login. Organization, visibility, and forget filters are applied before records reach the LLM. Client metadata and dataset time hints are also restricted to readable records.

**Deployment limitation:** the SQLite database is local and is not encrypted by this application. Anyone who can read the database file or run code as the same OS user can bypass the chat-layer filters. Do not deploy this terminal mode as a multi-user security boundary on a shared machine.

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
