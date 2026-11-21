#!/usr/bin/env python3
"""A deliberately dumb solution (no model). It exists only to prove the harness and scorer run.

  ingest --day N                 appends that day's records to a local JSON store
  brief --person P --date D      one {"status":"nothing_new"} object per meeting of P on D
  ask --person P --at T --ask Q  {"answer": null, ...}
  forget --person P --what W     no-op (prints {"ok": true})

Store: $R3_DUMMY_STORE, default ./.r3_dummy_store.json in the current directory.
Pack root: $R3_PACK, else the current directory if it has data/, else the folder above this script.
"""
import argparse, json, os, sys
from datetime import datetime, timedelta

ZONES = {'Asia/Kolkata': timedelta(hours=5, minutes=30), 'Europe/London': timedelta(0)}
USAGE = {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0, 'ms': 0}


def pack_root():
    env = os.environ.get('R3_PACK')
    if env and os.path.isdir(os.path.join(env, 'data')):
        return os.path.abspath(env)
    if os.path.isdir(os.path.join(os.getcwd(), 'data')):
        return os.getcwd()
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def store_path():
    return os.environ.get('R3_DUMMY_STORE') or os.path.join(os.getcwd(), '.r3_dummy_store.json')


def load():
    p = store_path()
    if os.path.isfile(p):
        return json.load(open(p, encoding='utf-8'))
    return {'days': [], 'records': []}


def zone_of(person):
    try:
        people = json.load(open(os.path.join(pack_root(), 'data', 'people.json'), encoding='utf-8'))
        for org in people.values():
            for p in org['people']:
                if p['id'] == person:
                    return p.get('zone', 'Asia/Kolkata')
    except (OSError, ValueError, KeyError):
        pass
    return 'Asia/Kolkata'


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('ingest'); s.add_argument('--day', type=int, required=True)
    s = sub.add_parser('brief'); s.add_argument('--person', required=True); s.add_argument('--date', required=True)
    s = sub.add_parser('ask'); s.add_argument('--person', required=True); s.add_argument('--at', required=True); s.add_argument('--ask', required=True)
    s = sub.add_parser('forget'); s.add_argument('--person', required=True); s.add_argument('--what', required=True)
    a = ap.parse_args()

    if a.cmd == 'ingest':
        st = load() if a.day != 1 else {'days': [], 'records': []}  # day 1 starts a fresh store
        if a.day in st['days']:
            print(json.dumps({'ok': True, 'skipped': 'already ingested'})); return
        path = os.path.join(pack_root(), 'data', 'days', f'day-{a.day:02d}.jsonl')
        with open(path, encoding='utf-8') as f:
            st['records'].extend(json.loads(l) for l in f if l.strip())
        st['days'].append(a.day)
        with open(store_path(), 'w', encoding='utf-8') as f:
            json.dump(st, f)
        print(json.dumps({'ok': True, 'records': len(st['records'])}))
    elif a.cmd == 'brief':
        off = ZONES.get(zone_of(a.person), timedelta(0))
        out = []
        for r in load()['records']:
            if r.get('type') != 'event':
                continue
            if a.person not in (r.get('attendees') or []) and r.get('author') != a.person:
                continue
            start = datetime.strptime(r['start'], '%Y-%m-%dT%H:%M:%SZ') + off
            if start.date().isoformat() != a.date:
                continue
            out.append({'meeting_id': r['event_id'], 'status': 'nothing_new', 'changed': [], 'promises': [],
                        'open_these': [], 'question_to_ask': None, 'usage': dict(USAGE)})
        print(json.dumps(out))
    elif a.cmd == 'ask':
        print(json.dumps({'answer': None, 'matched': [], 'clarify': None, 'refused': None, 'usage': dict(USAGE)}))
    elif a.cmd == 'forget':
        print(json.dumps({'ok': True}))


if __name__ == '__main__':
    main()
