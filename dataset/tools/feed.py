#!/usr/bin/env python3
"""Print one day of the data pack to stdout.

  python3 tools/feed.py --day 3              # that day's records, one JSON object per line
  python3 tools/feed.py --day 3 --feedback   # that day's feedback lines instead

The pack root is found in this order: $R3_PACK, the current directory (if it has data/),
then the folder above this script. Python 3 standard library only.
"""
import argparse, os, sys


def pack_root():
    env = os.environ.get('R3_PACK')
    if env and os.path.isdir(os.path.join(env, 'data')):
        return os.path.abspath(env)
    if os.path.isdir(os.path.join(os.getcwd(), 'data')):
        return os.getcwd()
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def main():
    ap = argparse.ArgumentParser(description='Print one day of records (or feedback) as JSONL.')
    ap.add_argument('--day', type=int, required=True)
    ap.add_argument('--feedback', action='store_true', help='print feedback lines instead of records')
    a = ap.parse_args()
    sub = 'feedback' if a.feedback else 'days'
    path = os.path.join(pack_root(), 'data', sub, f'day-{a.day:02d}.jsonl')
    if not os.path.isfile(path):
        print(f"Day {a.day} is not in this pack (hidden days are replayed by the organisers).", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                sys.stdout.write(line if line.endswith('\n') else line + '\n')


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:  # e.g. piped into head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
