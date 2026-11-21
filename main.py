#!/usr/bin/env python3
"""CLI Entrypoint for MemoFlow: Meeting Brief Helper and Workspace Memory."""
import argparse, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from MemoFlow.config import PACK_ROOT, DATA_DIR
from MemoFlow.db import init_db, get_connection, insert_record
from MemoFlow.brief_engine import generate_briefs
from MemoFlow.ask_engine import answer_ask

def handle_ingest(day):
    # Day 1 starts a fresh store
    init_db(reset=(day == 1))
    conn = get_connection()
    cur = conn.cursor()

    # Ingest records for day
    day_file = os.path.join(DATA_DIR, 'days', f'day-{day:02d}.jsonl')
    count = 0
    if os.path.isfile(day_file):
        with open(day_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    insert_record(conn, rec, day)
                    count += 1

    # Ingest feedback from day - 1
    if day > 1:
        feedback_file = os.path.join(DATA_DIR, 'feedback', f'day-{day-1:02d}.jsonl')
        if os.path.isfile(feedback_file):
            with open(feedback_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        fb = json.loads(line)
                        cur.execute('''
                        INSERT INTO feedback (day, person, type, words, meeting, topic, verdict)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            fb.get('day'),
                            fb.get('person'),
                            fb.get('type'),
                            fb.get('words'),
                            fb.get('meeting'),
                            fb.get('topic'),
                            fb.get('verdict')
                        ))
                        # If feedback is a forget line
                        if fb.get('type') == 'forget':
                            cur.execute('INSERT INTO forgets (person, what) VALUES (?, ?)',
                                        (fb.get('person'), fb.get('words')))

    conn.commit()
    conn.close()
    print(json.dumps({'ok': True, 'day': day, 'records': count}))

def handle_brief(person, date):
    briefs = generate_briefs(person, date)
    print(json.dumps(briefs, ensure_ascii=False))

def handle_ask(person, at, ask):
    result = answer_ask(person, at, ask)
    print(json.dumps(result, ensure_ascii=False))

def handle_forget(person, what):
    init_db(reset=False)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('INSERT INTO forgets (person, what) VALUES (?, ?)', (person, what))
    conn.commit()
    conn.close()
    print(json.dumps({'ok': True}))

def main():
    ap = argparse.ArgumentParser(description="MemoFlow: Meeting brief helper & question answering.")
    sub = ap.add_subparsers(dest='cmd', required=True)

    # Ingest
    s = sub.add_parser('ingest')
    s.add_argument('--day', type=int, required=True)

    # Brief
    s = sub.add_parser('brief')
    s.add_argument('--person', required=True)
    s.add_argument('--date', required=True)

    # Ask
    s = sub.add_parser('ask')
    s.add_argument('--person', required=True)
    s.add_argument('--at', required=True)
    s.add_argument('--ask', required=True)

    # Forget
    s = sub.add_parser('forget')
    s.add_argument('--person', required=True)
    s.add_argument('--what', required=True)

    args = ap.parse_args()

    if args.cmd == 'ingest':
        handle_ingest(args.day)
    elif args.cmd == 'brief':
        handle_brief(args.person, args.date)
    elif args.cmd == 'ask':
        handle_ask(args.person, args.at, args.ask)
    elif args.cmd == 'forget':
        handle_forget(args.person, args.what)

if __name__ == '__main__':
    main()
