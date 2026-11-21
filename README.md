# MemoFlow

A lightweight workplace-memory assistant. Ask questions about meetings, people, clients, tasks and decisions. MemoFlow searches the bundled dataset using **Python + SQLite** and answers with source record IDs.

## 1. Requirements

- Python 3.10+ (Python 3.12 recommended)
- An LLM API key from a supported OpenAI-compatible provider (Groq is preconfigured as the example)

No `pip install` or third-party Python packages are required.

## 2. Download and run

**Windows (PowerShell)**

```powershell
git clone https://github.com/rnaveenpatil/MemoFlow.git
cd MemoFlow
copy .env.example .env
notepad .env
python main.py
```

**macOS / Linux**

```bash
git clone https://github.com/rnaveenpatil/MemoFlow.git
cd MemoFlow
cp .env.example .env
nano .env
python3 main.py
```

In `.env`, add your provider's API key and a model ID enabled for your account:

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL_ID=your-provider-model-id
LLM_API_KEY=your-api-key
```

Save the file, then run `python main.py` (Windows) or `python3 main.py` (macOS/Linux). Keep `.env` private; it is ignored by Git.

## 3. Chat

1. Select a workspace.
2. Select a dataset day, or press Enter for the latest available day.
3. Type your question at `You:`.

Examples:

```text
Who owns the billing task?
What changed after the last client meeting?
What did the team promise to deliver?
```

Chat commands: `/help`, `/day 3`, `/refresh`, `/exit`.

## 4. Important behavior

- The bundled dataset is in `dataset/data/`; it is imported into a local SQLite database on startup.
- Selecting Day N means **Days 1 through N**. Later-day records are excluded.
- Answers use records the current session is allowed to read and include source IDs.
- This terminal version is a workspace session, not employee login: only team-visible records are available. Private/restricted records stay blocked.
- The database is local and not encrypted. Do not use this terminal mode as a multi-user security boundary on a shared computer.

## 5. Tests and other commands

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Other CLI commands:

```bash
python main.py ingest --day 5
python main.py ask --person p02 --at 2026-11-06T18:00:00Z --ask "Who handles billing?"
python main.py brief --person p02 --date 2026-11-06
python main.py forget --person p02 --what "a specific subject"
```

The interactive chat (`python main.py`) is the recommended way to start.
