# Round 3: the meeting brief helper

Welcome. Read this file first. Then read `DATA_FORMAT.md`.

## The story in one minute

- Kitepoint Studio is a small agency. Its id in the data is `org_kp`.
- It has 25 people and three clients.
- Every day the team sends mails, chats, writes docs, edits sheets and moves tasks.
- People are busy. Before a client meeting they want to know one thing:
  "What changed since the last time I met this client?"
- Your program reads the work, day by day.
- Then it writes a short brief before each meeting.
- It also answers short questions, like "Who owns billing for NB?".
- Another company, Brightwave Media (`org_bw`), also appears in the data.
  Its records belong to Brightwave people only.

## What is in the zip

```
pack/
  README.md            <- this file
  DATA_FORMAT.md       <- every field, with real examples
  data/
    people.json        <- everyone, with role, team and time zone
    clients.json       <- the three clients
    days/day-01.jsonl ... day-05.jsonl       <- the work, one record per line
    feedback/day-01.jsonl ... day-05.jsonl   <- what people told the helper
    tasks/day-01.json ... day-05.json        <- the briefs and questions asked each day
  answers/
    day-01.json ... day-05.json              <- expected results for days 1 to 5
  tools/
    run_days.py        <- our harness: runs your program day by day
    score.py           <- our scorer: compares your outputs with answers/
    feed.py            <- prints one day of records (handy for looking)
    baseline_dummy.py  <- a dumb example solution
```

Words used below:

- **record**: one line in `data/days/day-NN.jsonl`. One mail, one chat, one task change, and so on.
- **day N**: day 1 is Monday 2 Nov 2026. Day 2 is 3 Nov. And so on.
- **harness**: our script that calls your program, in order, and saves what it prints.
- **brief**: a short JSON summary for one meeting.
- **ask**: one question from one person.

## Quick start (4 commands)

```
unzip pack.zip && cd pack
python3 tools/run_days.py --cmd "python3 tools/baseline_dummy.py" --days 1-5 --out runs/dummy
python3 tools/score.py --run runs/dummy --days 1-5
python3 tools/feed.py --day 1 | head -20
```

Only Python 3 is needed. The tools use the standard library only.

## Your program: 4 commands

Your program is one command, for example `python3 my_solution.py`.
The harness adds the arguments. Your program must support these four:

| command | what it does | what it prints |
|---|---|---|
| `<your program> ingest --day N` | Read day N. Save what you need. | Anything short, like `{"ok": true}` |
| `<your program> brief --person P --date D` | Brief person P for their meetings on date D. | A JSON list, one brief per meeting |
| `<your program> ask --person P --at ISO --ask "text"` | Answer one question from person P, asked at time ISO. | One JSON object |
| `<your program> forget --person P --what "text"` | Person P asks you to forget something. | `{"ok": true}` |

Rules for all four:

- Print JSON to stdout. Only JSON. Put logs on stderr.
- Exit with code 0.
- Each call is a new process. Keep memory in local files or a local database.
- `P` is a person id like `p02`. `D` is a date like `2026-11-05`. `ISO` is UTC, like `2026-11-04T18:00:00Z`.
- Find the data folder from `$R3_PACK`. If it is not set, use the current folder.

The exact output fields are in `DATA_FORMAT.md`.

## The order of calls

For each day N, the harness does this:

1. `ingest --day N`
2. `forget ...` for each forget line that arrived (see `DATA_FORMAT.md`).
3. `brief ...` for each brief in `data/tasks/day-NN.json`.
4. `ask ...` for each question in `data/tasks/day-NN.json`.

Important timing:

- After day N is ingested, briefs are asked for meetings on the **next** date (day N+1).
- Feedback written on day N reaches you with `ingest --day N+1`.
  Read `data/feedback/day-(N-1).jsonl` when you ingest day N. Not earlier.

## Run our harness on your program

```
python3 tools/run_days.py --cmd "python3 my_solution.py" --days 1-5 --out runs/mine
```

- Outputs are saved in `runs/mine/day-NN/`.
- Every call is logged in `runs/mine/log.jsonl`, with time taken and errors.
- If your program prints something that is not JSON, it is saved as `.txt` and marked invalid.
- Default time limit per call: 120 seconds. Change it with `--timeout`.
- `ingest --day 1` should start a fresh store. The harness can run many times.

## Score your run

```
python3 tools/score.py --run runs/mine --days 1-5
```

It compares your outputs with `answers/`. It prints a score per day and per part.

## The dummy baseline

`tools/baseline_dummy.py` is a dumb solution. It uses no model.

- It says "nothing new" for every meeting.
- It answers `null` to every question.

It scores low **on purpose**. It only proves that the harness and scorer work.
Copy its argument parsing if you like. Do not copy its answers.

## What `answers/` contains

- Expected results for **days 1 to 5 only**.
- Use them to check your work and to understand what a good brief looks like.
- Do not hardcode them. The final score does not use these days alone.

## The hidden days

- Days 6 to 15 are **not** in this pack.
- The organisers replay your program on all 15 days, with the same harness:
  `python3 tools/run_days.py --cmd "<your command>" --days 1-15 --out ...`
- New people, new changes and new questions can appear on those days.
- So your program must work for any day, not just days 1 to 5.

## Token limits and usage

A **token** is a small piece of text that a language model reads or writes.
Roughly 4 characters of English is 1 token.

- **Brief**: at most **8,000 input tokens** per brief (for each meeting).
- **Ask**: at most **4,000 input tokens** per question.
- Put real numbers in the `usage` field of every output: input tokens, output tokens, cost in USD, time in ms.
- If you make two model calls for one brief, add them up.
- Report honestly. We check usage during the live session.
- If you use no model for a call, report 0 tokens.

We also score cost. A cheap, correct brief beats an expensive one.

## Do I need an LLM?

Yes, for the language parts.

Simple code is good at:

- reading JSON,
- comparing dates and times,
- matching ids like `p02`, `t-nb-05` or `northbeam`,
- picking the records that belong to one client.

Simple code **cannot reliably** understand:

- corrections written in plain words, like "No, Arjun owns billing now",
- Hinglish promises, like "kal tak bhej dunga" (= "I will send it by tomorrow"),
- nicknames for clients, like "NB" or "the London account",
- preferences, like "Max 5 changes for me",
- what a question really means,
- text that tries to give your program orders.

An **LLM** (large language model) can. Use any model you like:

- an API: OpenAI, Anthropic, Gemini, Groq, and others;
- a local model: ollama, llama.cpp;
- a command-line tool, for example `claude -p`.

The trick: **send the model only what it needs.**

- Use code first to pick the few records that matter.
- Then send those few records to the model.
- Sending a whole day will break the token limit and cost a lot.

Usage tokens:

- Most APIs return token counts. Use them.
- If your tool does not report tokens, estimate: characters / 4.
- If you estimate, say so in your own README.

Tell us which model and which API you use. The organisers allow only that network
access when they replay your program.

## What to submit

- Your code, in a git repository.
- One command that runs it, like `python3 my_solution.py`.
- A short README: how to install, the model you use, how you count tokens.
- A short design note: how you pick records, what you send to the model, and why.

## FAQ

**1. Can I use any language?**
Yes. Wrap it in one command, like `node main.js` or `./my_binary`.

**2. Can I use a database?**
Yes, local only. SQLite, files, anything on the same machine. No cloud database.

**3. Can I read ahead to future days?**
No. The pack has only days 1 to 5. On replay, your program must work one day at a time.
On `ingest --day N`, read day N and older days only.

**4. What if a person has no meeting on that date?**
Print an empty list: `[]`.

**5. What if nothing changed for a meeting?**
Return that meeting with `"status": "nothing_new"` and empty lists.
Saying "nothing new" when it is true is a good answer.

**6. What if a question is unclear?**
Do not guess. Fill `clarify` with a short question and the options you see.

**7. What if the person must not see the answer?**
Fill `refused` with a short reason. Never quote what they cannot see.

**8. Two records disagree. Which one wins?**
Usually the newest one from a trusted person. A correction from the person you brief also counts.
Think like a careful assistant.

**9. Can I change the harness or the scorer?**
You can read them. The organisers use their own copy, so changes do not help.

**10. Do I need to cite sources?**
Yes. Every line in a brief and every answer lists the record ids it came from.
A claim with no source scores lower.
