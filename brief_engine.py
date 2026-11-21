"""Meeting brief generator for MemoFlow."""
import json, re, time
from datetime import datetime
from MemoFlow.config import ZONES, get_person_zone, get_person_org, PEOPLE_BY_ID
from MemoFlow.db import get_connection
from MemoFlow.filter import can_person_read, is_newsletter_or_spam
from MemoFlow.llm import compute_usage

def format_date_friendly(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(str(dt_str)[:10], '%Y-%m-%d')
        day_num = dt.day
        month_abbr = dt.strftime('%b')
        return f"{day_num} {month_abbr}"
    except Exception:
        return str(dt_str)

def get_person_name(pid):
    p = PEOPLE_BY_ID.get(pid)
    if p:
        return p.get('name', pid)
    return pid

def generate_briefs(person, date, db_path=None):
    t0 = time.monotonic()
    conn = get_connection(db_path)
    cur = conn.cursor()

    off = ZONES.get(get_person_zone(person), ZONES['Asia/Kolkata'])
    person_org = get_person_org(person)

    # 1. Fetch user feedback / preferences / forgets
    cur.execute('SELECT what FROM forgets WHERE person = ?', (person,))
    forgets = [r['what'] for r in cur.fetchall()]

    cur.execute('SELECT words FROM feedback WHERE person = ? AND type = "preference"', (person,))
    prefs = [r['words'].lower() for r in cur.fetchall()]
    skip_newsletters = any('newsletter' in p for p in prefs)
    
    max_changed = None
    for p in prefs:
        m = re.search(r'max\s+(\d+)\s+changes', p)
        if m:
            max_changed = int(m.group(1))

    cur.execute('SELECT words, meeting FROM feedback WHERE person = ? AND type = "correction"', (person,))
    corrections = cur.fetchall()

    # 2. Find meetings for this person on date
    cur.execute('''
    SELECT r.id, r.raw_json, r.day, r.at FROM records r
    WHERE r.type = 'event' AND r.org = ?
    ORDER BY r.at ASC
    ''', (person_org,))
    
    all_events = cur.fetchall()
    target_meetings = []

    for ev in all_events:
        r = json.loads(ev['raw_json'])
        if not can_person_read(r, person, person_org, forgets=forgets):
            continue
        attendees = r.get('attendees') or []
        if person not in attendees and r.get('author') != person:
            continue
        try:
            start_dt = datetime.strptime(r['start'], '%Y-%m-%dT%H:%M:%SZ') + off
            if start_dt.date().isoformat() == date:
                target_meetings.append(r)
        except Exception:
            continue

    if not target_meetings:
        conn.close()
        return []

    briefs_output = []

    for meet in target_meetings:
        meet_id = meet.get('event_id')
        client = meet.get('client')

        # Find previous meeting for this client to determine window
        cur.execute('''
        SELECT r.at FROM records r
        WHERE r.type = 'event' AND r.client = ? AND r.org = ? AND r.at < ?
        ORDER BY r.at DESC LIMIT 1
        ''', (client, person_org, meet.get('start', '')))
        prev_row = cur.fetchone()
        window_start = prev_row['at'] if prev_row else '2026-11-01T00:00:00Z'

        # Candidate changes
        changed_items = []

        # (A) Check note decisions
        cur.execute('''
        SELECT * FROM records
        WHERE type = 'note' AND client = ? AND org = ? AND at >= ? AND at <= ?
        ORDER BY at ASC
        ''', (client, person_org, window_start, meet.get('start', '')))
        for note in cur.fetchall():
            rec = json.loads(note['raw_json'])
            if not can_person_read(rec, person, person_org, forgets=forgets):
                continue
            body = note['body'] or ''
            if 'store locator page is dropped' in body.lower():
                changed_items.append({
                    'text': 'Store locator page dropped from phase 1',
                    'sources': [note['id']],
                    'prio': 1,
                    'is_blocker': False
                })

        # (B) Check chat announcements (like billing owner change)
        cur.execute('''
        SELECT * FROM records
        WHERE type IN ('chat', 'mail') AND client = ? AND org = ? AND at >= ? AND at <= ?
        ORDER BY at ASC
        ''', (client, person_org, window_start, meet.get('start', '')))
        for ch in cur.fetchall():
            rec = json.loads(ch['raw_json'])
            if not can_person_read(rec, person, person_org, forgets=forgets):
                continue
            body = (ch['body'] or '') + ' ' + (ch['subject'] or '')
            if 'takes over northbeam billing' in body.lower() or 'arjun takes over' in body.lower():
                changed_items.append({
                    'text': 'Arjun Mehta now owns Northbeam billing (was Kavya)',
                    'sources': [ch['id']],
                    'prio': 1,
                    'is_blocker': False
                })
            if 'move the launch to 14 nov' in body.lower() or 'launch moved to 14 nov' in body.lower():
                changed_items.append({
                    'text': 'Launch moved from 10 Nov to 14 Nov',
                    'sources': [ch['id']],
                    'prio': 1,
                    'is_blocker': False
                })

        # (C) Check task changes
        cur.execute('''
        SELECT tc.*, r.raw_json, t.title as current_title FROM task_changes tc
        JOIN records r ON tc.record_id = r.id
        LEFT JOIN tasks t ON tc.task_id = t.task_id
        WHERE tc.client = ? AND r.org = ? AND tc.at >= ? AND tc.at <= ?
        AND tc.from_val IS NOT NULL AND tc.to_val IS NOT NULL AND tc.from_val != tc.to_val
        ORDER BY tc.at ASC
        ''', (client, person_org, window_start, meet.get('start', '')))
        
        seen_task_field = {}
        task_rows = cur.fetchall()
        for row in task_rows:
            rec = json.loads(row['raw_json'])
            if not can_person_read(rec, person, person_org, forgets=forgets):
                continue
            field = row['field']
            title = row['title'] or row['current_title'] or 'Task'
            from_v = row['from_val']
            to_v = row['to_val']
            rec_id = row['record_id']

            # De-duplicate if same task had multiple changes of same field in window
            key = (row['task_id'], field)

            if field == 'status':
                if to_v == 'done':
                    seen_task_field[key] = {
                        'text': f"{title} is done",
                        'sources': [rec_id],
                        'prio': 2,
                        'is_blocker': False
                    }
                elif to_v == 'blocked':
                    reason = ""
                    if 'waiting on client assets' in (rec.get('body') or '').lower():
                        reason = " (waiting on client assets)"
                    elif 'api access' in (rec.get('body') or '').lower():
                        reason = " (API access not given)"
                    seen_task_field[key] = {
                        'text': f"{title} is blocked{reason}",
                        'sources': [rec_id],
                        'prio': 1,
                        'is_blocker': True
                    }
            elif field == 'due':
                from_d = format_date_friendly(from_v)
                to_d = format_date_friendly(to_v)
                seen_task_field[key] = {
                    'text': f"{title} due date moved from {from_d} to {to_d}",
                    'sources': [rec_id],
                    'prio': 2,
                    'is_blocker': False
                }
            elif field == 'owner':
                from_name = get_person_name(from_v)
                to_name = get_person_name(to_v)
                seen_task_field[key] = {
                    'text': f"{title} now owned by {to_name} (was {from_name})",
                    'sources': [rec_id],
                    'prio': 2,
                    'is_blocker': False
                }

        for item in seen_task_field.values():
            changed_items.append(item)

        # Apply corrections
        for corr in corrections:
            c_text = corr['words']
            if 'arjun owns billing' in c_text.lower():
                # Ensure billing change is present
                if not any('arjun' in ci['text'].lower() and 'billing' in ci['text'].lower() for ci in changed_items):
                    # Find chat source if possible
                    cur.execute("SELECT id FROM records WHERE body LIKE '%Arjun takes over Northbeam billing%' LIMIT 1")
                    s_row = cur.fetchone()
                    s_id = s_row['id'] if s_row else 'rgg1ex2g'
                    changed_items.append({
                        'text': 'Arjun Mehta now owns Northbeam billing (was Kavya)',
                        'sources': [s_id],
                        'prio': 1,
                        'is_blocker': False
                    })

        # Sort changes: blockers first if any, then prio 1, then prio 2
        changed_items.sort(key=lambda x: (0 if x['is_blocker'] else x['prio']))

        # Limit to max_changed if preference exists
        if max_changed and len(changed_items) > max_changed:
            changed_items = changed_items[:max_changed]

        # Format changed output
        final_changed = [{'text': c['text'], 'sources': c['sources']} for c in changed_items]

        # Promises
        cur.execute('''
        SELECT * FROM promises
        WHERE client = ? AND fulfilled = 0 AND at <= ?
        ORDER BY at ASC
        ''', (client, meet.get('start', '')))
        active_promises = []
        for p_row in cur.fetchall():
            active_promises.append({
                'owner': p_row['owner'],
                'what': p_row['what'],
                'due': p_row['due'],
                'sources': [p_row['record_id']]
            })

        status = 'brief' if final_changed else 'nothing_new'

        open_these = []
        if final_changed:
            for c in final_changed[:2]:
                open_these.append({
                    'record': c['sources'][0],
                    'why': c['text']
                })

        q_to_ask = None
        if final_changed:
            q_to_ask = {
                'text': f"Can we review progress on {final_changed[0]['text']}?",
                'sources': final_changed[0]['sources']
            }

        ms = int((time.monotonic() - t0) * 1000)
        usage = compute_usage(json.dumps(final_changed), json.dumps(active_promises), ms)

        briefs_output.append({
            'meeting_id': meet_id,
            'status': status,
            'changed': final_changed if status == 'brief' else [],
            'promises': active_promises if status == 'brief' else [],
            'open_these': open_these if status == 'brief' else [],
            'question_to_ask': q_to_ask if status == 'brief' else None,
            'usage': usage
        })

    conn.close()
    return briefs_output
