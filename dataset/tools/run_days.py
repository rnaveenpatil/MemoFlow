#!/usr/bin/env python3
"""Replay the pack day by day against your program and save every output.

  python3 tools/run_days.py --cmd "python3 my_solution.py" --days 1-5 --out runs/mine [--timeout 120]

For each day d, in order:
  1. <cmd> ingest --day d
  2. for each "forget" line in data/feedback/day-(d-1).jsonl: <cmd> forget --person P --what "<words>"
  3. for each brief task in data/tasks/day-d.json: <cmd> brief --person P --date D
       -> <out>/day-NN/brief-<person>-<date>.json
  4. for each ask in data/tasks/day-d.json: <cmd> ask --person P --at ISO --ask "text"
       -> <out>/day-NN/ask-<qid>.json
Stdout that is not valid JSON is saved as .txt instead and marked invalid in the log.
Every call is logged to <out>/log.jsonl: day, kind, argv, exit code, wall ms, stderr tail, valid.

Your program runs with the current directory as its working directory. Commands are split with
shlex and run without a shell. Pack root: $R3_PACK, else the current directory if it has data/,
else the folder above this script. Python 3 standard library only.
"""
import argparse, json, os, shlex, subprocess, sys, time


def pack_root():
    env = os.environ.get('R3_PACK')
    if env and os.path.isdir(os.path.join(env, 'data')):
        return os.path.abspath(env)
    if os.path.isdir(os.path.join(os.getcwd(), 'data')):
        return os.getcwd()
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def parse_days(s):
    out = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def safe(s):
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(s))


class Runner:
    def __init__(self, base, out, timeout):
        self.base, self.out, self.timeout = base, out, timeout
        self.log = open(os.path.join(out, 'log.jsonl'), 'a', encoding='utf-8')

    def call(self, day, kind, args, save_as=None):
        argv = self.base + args
        t0 = time.monotonic()
        try:
            p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout,
                               cwd=os.getcwd())
            code, so, se = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            code, so, se = 'timeout', e.stdout or b'', (e.stderr or b'') + f'\n[run_days] timed out after {self.timeout}s'.encode()
        except FileNotFoundError as e:
            code, so, se = 'not_found', b'', str(e).encode()
        ms = int((time.monotonic() - t0) * 1000)
        so = so.decode('utf-8', 'replace')
        se = se.decode('utf-8', 'replace')
        entry = {'day': day, 'kind': kind, 'args': args, 'exit': code, 'ms': ms, 'stderr_tail': se[-800:]}
        ok = code == 0
        if save_as:
            try:
                json.loads(so)
                valid = True
            except ValueError:
                valid = False
            path = save_as + ('.json' if valid else '.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(so)
            entry['file'] = os.path.relpath(path, self.out)
            entry['valid'] = valid
            ok = ok and valid
        self.log.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self.log.flush()
        return ok, entry


def main():
    ap = argparse.ArgumentParser(description='Replay days against a solution command and save outputs.')
    ap.add_argument('--cmd', required=True, help='your program, e.g. "python3 my_solution.py"')
    ap.add_argument('--days', default='1-5', help='e.g. 1-5 or 1,2,3')
    ap.add_argument('--out', required=True, help='output folder, e.g. runs/mine')
    ap.add_argument('--timeout', type=float, default=120, help='seconds per call (default 120)')
    a = ap.parse_args()

    root = pack_root()
    data = os.path.join(root, 'data')
    days = parse_days(a.days)
    if not days:
        sys.exit('no days given')
    if days[0] != 1:
        print(f"note: starting at day {days[0]}; days before it are not ingested by this run.", file=sys.stderr)
    base = shlex.split(a.cmd)
    os.makedirs(a.out, exist_ok=True)
    log_path = os.path.join(a.out, 'log.jsonl')
    if os.path.exists(log_path):
        os.remove(log_path)  # one log per run
    r = Runner(base, a.out, a.timeout)
    print(f"pack: {root}\nrun:  {os.path.abspath(a.out)}\ncmd:  {base}")
    total_bad = 0
    for d in days:
        if not os.path.isfile(os.path.join(data, 'days', f'day-{d:02d}.jsonl')):
            print(f"Day {d} is not in this pack (hidden days are replayed by the organisers). Stopping.", file=sys.stderr)
            sys.exit(2)
        dd = os.path.join(a.out, f'day-{d:02d}')
        os.makedirs(dd, exist_ok=True)
        t0 = time.monotonic()
        bad = []
        ok, e = r.call(d, 'ingest', ['ingest', '--day', str(d)])
        if not ok:
            bad.append(f"ingest exit={e['exit']}")
        forgets = [x for x in read_jsonl(os.path.join(data, 'feedback', f'day-{d-1:02d}.jsonl')) if x.get('type') == 'forget']
        for x in forgets:
            ok, e = r.call(d, 'forget', ['forget', '--person', x['person'], '--what', x['words']])
            if not ok:
                bad.append(f"forget exit={e['exit']}")
        tpath = os.path.join(data, 'tasks', f'day-{d:02d}.json')
        tasks = json.load(open(tpath, encoding='utf-8')) if os.path.isfile(tpath) else {'briefs': [], 'asks': []}
        for b in tasks.get('briefs', []):
            ok, e = r.call(d, 'brief', ['brief', '--person', b['person'], '--date', b['date']],
                           save_as=os.path.join(dd, f"brief-{safe(b['person'])}-{safe(b['date'])}"))
            if not ok:
                bad.append(f"brief {b['person']} {b['date']} exit={e['exit']} valid={e.get('valid')}")
        for q in tasks.get('asks', []):
            ok, e = r.call(d, 'ask', ['ask', '--person', q['person'], '--at', q['at'], '--ask', q['ask']],
                           save_as=os.path.join(dd, f"ask-{safe(q['qid'])}"))
            if not ok:
                bad.append(f"ask {q['qid']} exit={e['exit']} valid={e.get('valid')}")
        secs = time.monotonic() - t0
        total_bad += len(bad)
        print(f"day {d:2d}: ingest + {len(forgets)} forget, {len(tasks.get('briefs', []))} briefs, "
              f"{len(tasks.get('asks', []))} asks in {secs:.1f}s" + (f"  PROBLEMS: {len(bad)}" if bad else "  ok"))
        for msg in bad[:5]:
            print(f"        - {msg}")
    print(f"done. log: {log_path}" + (f"  ({total_bad} problem calls, see log)" if total_bad else ''))


if __name__ == '__main__':
    main()
