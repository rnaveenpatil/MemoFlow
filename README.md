# MemoFlow: Autonomous Meeting Brief & Context Assistant

MemoFlow is a lightweight, high-performance meeting assistant built with **Python + SQLite (with FTS5 full-text search)**. It processes workspace communication records, tracks task and document states across days, generates client meeting briefs, and answers ad-hoc questions with privacy boundaries and source citations.

## Quick start: chat-first mode

Run:

```bash
python main.py
```

1. Select a JSONL day file. You do not enter a person ID or employee name to start.
2. MemoFlow detects the day from the filename and cumulatively imports Days 1 through that day into its persistent SQLite database. It never imports future days.
3. Chat normally. Mention people and clients by name; the LLM resolves names against the loaded workspace directory and validates returned IDs before using them.
4. Give explicit memory instructions naturally, for example: "Remember that the launch review moved to Thursday" or "Correct the workspace note: the owner is Priya, not Arjun." MemoFlow stores these as user-provided updates with provenance. They are not silently rewritten into the original JSONL files or represented as independently verified dataset records.
5. Use `/file` to select and ingest another day file, or `/exit` to quit.

MemoFlow's identity-free chat mode is deliberately limited to team-visible records. Since no employee identity is authenticated, private and restricted records are not exposed. A person's name mentioned in a question is not treated as the identity of the person asking. If the dataset contains multiple organizations or no valid organization directory, MemoFlow fails closed instead of searching across organizations.

Keep earlier day files together in the selected file's folder, or place them under `data/days/`. Filenames must contain a day marker such as `day-01.jsonl`, `day-2.jsonl`, or `Day 3.jsonl`. Missing earlier days cause an error rather than silently creating incomplete history. Imported data and explicit user-provided memory updates are stored in SQLite; source JSONL files remain unchanged.

**Privacy:** every dataset query is filtered by organization, visibility (`team`, `private`, `restricted`), as-of time, and forget rules before evidence reaches the LLM. User-provided updates are separately labelled and cited so they are not confused with original dataset records.


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
