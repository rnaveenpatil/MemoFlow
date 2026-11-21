# Data format

This file explains every file and every field. The examples are real lines from the data.
Long `body` text is cut with `...` here, only to save space.

## Basic ideas

- **JSONL**: one JSON object per line. `data/days/*.jsonl` and `data/feedback/*.jsonl` use it.
- **id**: every record has a unique id, like `"r9btn7pq"`. You cite records by this id.
- **Time**: every time in the data is **UTC**, in ISO format, like `"2026-11-04T08:15:00Z"`.
  The `Z` at the end means UTC.
- **Zones**: each person has a time zone in `people.json`.
  `Asia/Kolkata` is UTC + 5:30. `Europe/London` is UTC + 0:00 in November.
  "Today", "tomorrow" and "last week" mean the person's own local time.
- **Day N**: day 1 = Monday 2 Nov 2026. Day N holds records whose local time falls on that day.

## people.json

Two organisations. Each person has an id, a name, a role and a zone.

```
{"org_kp": {"name": "Kitepoint Studio", "people": [
   {"id": "p02", "name": "Meera Iyer", "role": "manager", "team": "client", "zone": "Asia/Kolkata"}, ...]},
 "org_bw": {"name": "Brightwave Media", "people": [ ... ]}}
```

- `p01` to `p25` are Kitepoint people. `q01` to `q08` are Brightwave people.
- Two people can share a first name. Use the id to tell them apart.
- People outside both companies look like `ext:anita.shah@northbeam.in` (client staff, vendors, mailers).
- `system` is the author of automatic notifications.

## clients.json

```
[{"id": "northbeam", "name": "Northbeam Retail"},
 {"id": "cobaltline", "name": "Cobaltline Logistics"},
 {"id": "alderpoint", "name": "Alderpoint Foods"}]
```

People often use short names for clients. Your program must work that out.

## Fields every record has

| field | meaning |
|---|---|
| `id` | unique record id. Cite this. |
| `org` | `org_kp` or `org_bw`. Which company the record belongs to. |
| `type` | `mail`, `chat`, `doc`, `sheet`, `task`, `event`, `note` or `notification` |
| `at` | when it happened, UTC |
| `author` | person id, `ext:...` address, or `system` |
| `client` | client id, or `null` if the record is not tagged with a client |
| `visibility` | `team`, `private` or `restricted` (see below) |
| `readers` | only for `restricted`: the list of person ids who may see it |
| `body` | the text |

`client` is a hint, not a promise. Some records talk about a client without the tag.

## Visibility rules

| visibility | who may see it |
|---|---|
| `team` | everyone in the same `org` |
| `private` | only the `author` |
| `restricted` | only the people listed in `readers` |

And always:

- A person sees only records of **their own org**.
- If a person cannot see a record, it must not shape their brief or answer. Do not cite it. Do not hint at it.

A private record (real):

```
{"id": "r8nxxg7m", "org": "org_kp", "type": "chat", "at": "2026-11-05T12:00:00Z", "author": "p03", "client": "cobaltline", "visibility": "private", "channel": "dm:self", "body": "Honestly I think Cobaltline will churn after UAT. Keep this between us."}
```

A restricted record looks like this (made-up example, shape only):

```
{"id": "rxxxxxxx", "org": "org_kp", "type": "note", "at": "...", "author": "p05", "client": null, "visibility": "restricted", "readers": ["p05", "p01"], "body": "..."}
```

## Record types

### mail
Extra fields: `to` (list of ids or addresses), `subject`.
```
{"id": "r22xps8b", "org": "org_kp", "type": "mail", "at": "2026-11-03T04:40:00Z", "author": "p17", "client": "northbeam", "visibility": "team", "to": ["ext:anita.shah@northbeam.in"], "subject": "Re: Northbeam Retail – next steps", "body": "Hi team, I will send the media plan by Thursday."}
```
Later a delivery can close a promise:
```
{"id": "r9btn7pq", "org": "org_kp", "type": "mail", "at": "2026-11-04T08:15:00Z", "author": "p08", "client": "northbeam", "visibility": "team", "to": ["ext:anita.shah@northbeam.in"], "subject": "The UTM sheet", "body": "Sharing the UTM sheet as promised. Let me know if anything is missing."}
```

### chat
Extra field: `channel`, like `#accounts`, `#northbeam`, or `dm:self` (a note to oneself).
```
{"id": "r848kac6", "org": "org_kp", "type": "chat", "at": "2026-11-05T05:00:00Z", "author": "p09", "client": "northbeam", "visibility": "team", "channel": "#northbeam", "body": "the store page wireframes kal tak bhej dunga"}
```
"kal tak bhej dunga" is Hinglish for "I will send it by tomorrow". That is a promise.

### doc
Extra fields: `doc_id` (same for all versions), `version` (1, 2, ...), `title`.
A new version is a new record with the **full** text. Compare versions to see what changed.
```
{"id": "rx5m95ed", "org": "org_kp", "type": "doc", "at": "2026-11-02T03:40:00Z", "author": "p07", "client": "northbeam", "visibility": "team", "doc_id": "d-nb-launch", "version": 1, "title": "Northbeam launch plan", "body": "Northbeam launch plan.\nLaunch date: 10 Nov 2026.\nBilling contact: Kavya Nair (accounts).\n..."}
```

### sheet
Extra fields: `sheet_id`, `version`, `name`, `cells` (cell name -> value, all strings).
Each version holds the cells as they are now.
```
{"id": "rq0pu1dc", "org": "org_kp", "type": "sheet", "at": "2026-11-02T04:10:00Z", "author": "p17", "client": "northbeam", "visibility": "team", "sheet_id": "s-nb-rev", "version": 1, "name": "Northbeam revenue", "cells": {"A3": "September", "B3": "37.5", "A4": "October", "B4": "42.0", "C1": "INR lakh"}, "body": "Northbeam revenue tracker"}
```

### task
Extra fields: `task_id`, `title`, `owner`, `due` (date), `status`, `change`.
- `owner`, `due` and `status` are the values **after** this change.
- `status` is one of `todo`, `in_progress`, `blocked`, `done`, `cancelled`.
- `change.field` is `created`, `comment`, `due`, `owner` or `status`. For the last three, `from` and `to` are given.
- `author` is who made the change. It can differ from the owner.
```
{"id": "rnm51pu1", "org": "org_kp", "type": "task", "at": "2026-11-04T11:40:00Z", "author": "p17", "client": "northbeam", "visibility": "team", "task_id": "t-nb-06", "title": "Analytics tagging", "owner": "p17", "due": "2026-11-14", "status": "todo", "change": {"field": "due", "from": "2026-11-11", "to": "2026-11-14"}, "body": "Need more time, moving the date."}
{"id": "r93gjw62", "org": "org_kp", "type": "task", "at": "2026-11-03T05:50:00Z", "author": "p03", "client": "cobaltline", "visibility": "team", "task_id": "t-cl-05", "title": "Ops report template", "owner": "p05", "due": "2026-11-11", "status": "todo", "change": {"field": "owner", "from": "p21", "to": "p05"}, "body": "Reassigning to Sameer."}
```

### event
A calendar meeting. Extra fields: `event_id`, `start` (UTC), `attendees`, `title`.
```
{"id": "re971wnz", "org": "org_kp", "type": "event", "at": "2026-11-02T03:00:00Z", "author": "p02", "client": "northbeam", "visibility": "team", "event_id": "ev-nb-me-04", "start": "2026-11-05T05:30:00Z", "attendees": ["p02", "p07", "ext:anita.shah@northbeam.in"], "title": "Northbeam weekly check-in", "body": "Northbeam weekly check-in"}
```
`start` 05:30 UTC = 11:00 in Kolkata. The meeting's date is the attendee's **local** date.

### note
Meeting notes. Extra field: `event_id` (the meeting the note belongs to).
```
{"id": "rqk04c4p", "org": "org_kp", "type": "note", "at": "2026-11-03T07:00:00Z", "author": "p02", "client": "northbeam", "visibility": "team", "event_id": "ev-nb-me-02", "body": "Northbeam check-in notes.\nDecision: store locator page is dropped from phase 1.\n..."}
```

### notification
Automatic messages. Extra field: `to`.
```
{"id": "rtupk4ku", "org": "org_kp", "type": "notification", "at": "2026-11-04T01:40:00Z", "author": "system", "client": null, "visibility": "team", "to": ["p11"], "body": "Disk usage at 71%"}
```

Note: some records (for example Brightwave ones) may miss optional fields like `channel`, `to` or `subject`.
Your code must not crash on a missing field.

## Feedback files

`data/feedback/day-NN.jsonl` holds what people told the helper on day N.
It reaches your program with `ingest --day N+1`. Each line has `day`, `person`, `type`, `words`.

| type | meaning | extra fields |
|---|---|---|
| `preference` | how this person wants their briefs from now on | none |
| `correction` | a fact in a brief was wrong; here is the right one | `meeting` |
| `verdict` | was one brief line useful? | `meeting`, `topic`, `verdict` (`kept` or `ignored`) |
| `forget` | forget something this person said | none |

Real lines:
```
{"day": 2, "person": "p02", "type": "preference", "words": "Skip newsletters in my briefs."}
{"day": 3, "person": "p02", "type": "correction", "meeting": "ev-nb-me-04", "words": "No, Arjun owns billing now, not Kavya."}
{"day": 5, "person": "p02", "type": "verdict", "meeting": "ev-nb-me-04", "topic": "Northstar Print poster offers", "verdict": "ignored", "words": "Not relevant. Northstar is a print vendor, not Northbeam."}
```
A forget line looks like this (shape only):
```
{"day": N, "person": "pXX", "type": "forget", "words": "Forget what I said about <something>."}
```
The harness also sends each forget line to you as `forget --person P --what "words"`.
After a forget, that thing must not appear in that person's briefs or answers.

## Tasks files

`data/tasks/day-NN.json` lists what is asked after day N is ingested.
```
{"briefs": [{"person": "p02", "date": "2026-11-03"}],
 "asks": [{"qid": "q01-02", "person": "p12", "at": "2026-11-02T18:00:00Z", "ask": "Who owns the NB Retail product feed fix?"}]}
```
- A brief `date` is always the next date (day N+1).
- The same person and date can be listed twice. Return the same answer each time.
- `at` is when the question is asked, in UTC. Answer as of that moment.

## Output: brief

`brief --person P --date D` prints a **JSON list**. One object per meeting P attends on date D.
No meetings? Print `[]`.

```
[{
  "meeting_id": "ev-nb-ne-05",
  "status": "brief",
  "changed": [
    {"text": "Analytics tagging due date moved from 11 Nov to 14 Nov", "sources": ["rnm51pu1"]}
  ],
  "promises": [
    {"owner": "p09", "what": "the store page wireframes", "due": "2026-11-06", "sources": ["r848kac6"]}
  ],
  "open_these": [{"record": "rnm51pu1", "why": "New due date for analytics tagging"}],
  "question_to_ask": {"text": "Can the tagging still be ready before launch?", "sources": ["rnm51pu1"]},
  "usage": {"input_tokens": 3120, "output_tokens": 240, "cost_usd": 0.0021, "ms": 1850}
}]
```

| field | meaning |
|---|---|
| `meeting_id` | the `event_id` of the meeting |
| `status` | `brief` if something changed since this person's last meeting with this client; else `nothing_new` |
| `changed` | what changed. Most important first. Each line has `text` and `sources` (record ids). |
| `promises` | promises still open: `owner` (person id), `what`, `due` (YYYY-MM-DD), `sources` |
| `open_these` | a few records worth opening before the meeting: `record` (id) and `why` |
| `question_to_ask` | one good question for the meeting, with `sources`. Can be `null`. |
| `usage` | `input_tokens`, `output_tokens`, `cost_usd`, `ms` (time taken) |

For `nothing_new`, use empty lists and `"question_to_ask": null`.

## Output: ask

`ask --person P --at ISO --ask "text"` prints **one JSON object**. Fill exactly one of
`answer`, `clarify`, `refused`. Set the other two to `null`.

```
{
  "answer": {"text": "Farhan Ali (p09) owns the product feed fix.", "sources": ["r3c3d22c"]},
  "matched": [{"phrase": "NB Retail product feed fix", "id": "t-nb-05", "sources": ["r3c3d22c"]}],
  "clarify": null,
  "refused": null,
  "usage": {"input_tokens": 900, "output_tokens": 40, "cost_usd": 0.0004, "ms": 700}
}
```

| field | meaning |
|---|---|
| `answer` | `{text, sources}`, or `null` |
| `matched` | what words in the question pointed to: `phrase`, `id` (person, client or task id), `sources` |
| `clarify` | `{question, options}` when the question is unclear, else `null`. `options` is a list of `{"id", "text"}`. |
| `refused` | `{reason}` when the person must not see the answer, else `null` |
| `usage` | same as in a brief |

A clarify example (shape only):
```
"clarify": {"question": "Which report do you mean?",
            "options": [{"id": "t-cl-05", "text": "Ops report template"}, {"id": "t-ap-01", "text": "November monthly report"}]}
```

If you have nothing to remember for a question, answer honestly with a short text, like
"I have nothing on that." Never invent a fact.
