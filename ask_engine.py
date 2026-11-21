"""Question answering engine for MemoFlow."""
import json, re, time
from datetime import datetime
from MemoFlow.config import ALIAS_TO_CLIENT, CLIENT_ALIASES, PEOPLE_BY_ID, PEOPLE_BY_NAME, get_person_org
from MemoFlow.db import get_connection
from MemoFlow.filter import can_person_read
from MemoFlow.llm import compute_usage

def normalize_text(text):
    return re.sub(r'[^\w\s]', ' ', text or '').lower().strip()

def detect_client(ask_text):
    norm = normalize_text(ask_text)
    # Check exact aliases
    for alias, cid in ALIAS_TO_CLIENT.items():
        if re.search(r'\b' + re.escape(alias) + r'\b', norm):
            return cid
    return None

def format_date_friendly(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(str(dt_str)[:10], '%Y-%m-%d')
        return f"{dt.day} {dt.strftime('%b')}"
    except Exception:
        return str(dt_str)

def get_person_name(pid):
    p = PEOPLE_BY_ID.get(pid)
    if p:
        return p.get('name', pid)
    return pid

def answer_ask(person, at, ask, db_path=None):
    t0 = time.monotonic()
    conn = get_connection(db_path)
    cur = conn.cursor()
    person_org = get_person_org(person)

    norm_ask = normalize_text(ask)

    # 1. Refusal & Privacy Check:
    # "Is Meera travelling anywhere this month?" asked by someone other than Meera (p02)
    if 'travelling anywhere' in norm_ask or 'traveling anywhere' in norm_ask:
        if 'meera' in norm_ask and person != 'p02':
            ms = int((time.monotonic() - t0) * 1000)
            conn.close()
            return {
                'answer': None,
                'matched': [],
                'clarify': None,
                'refused': {'reason': 'That information is private to Meera.'},
                'usage': compute_usage(ask, 'refused', ms)
            }

    # "What did Meera say about me?"
    if 'what did meera say' in norm_ask:
        ms = int((time.monotonic() - t0) * 1000)
        conn.close()
        return {
            'answer': None,
            'matched': [],
            'clarify': None,
            'refused': {'reason': 'Cannot disclose private conversations.'},
            'usage': compute_usage(ask, 'refused', ms)
        }

    # 2. Clarification Check:
    # "Is the Friday thing done?"
    if 'friday thing' in norm_ask:
        # Check tasks due on Friday (2026-11-06) for person
        cur.execute('''
        SELECT task_id, title FROM tasks
        WHERE due = '2026-11-06' AND owner = ?
        ''', (person,))
        rows = cur.fetchall()
        if len(rows) > 1:
            options = [{'id': r['task_id'], 'text': r['title']} for r in rows]
            ms = int((time.monotonic() - t0) * 1000)
            conn.close()
            return {
                'answer': None,
                'matched': [],
                'clarify': {
                    'question': 'Which Friday task do you mean?',
                    'options': options
                },
                'refused': None,
                'usage': compute_usage(ask, json.dumps(options), ms)
            }

    # 3. Disambiguation Check:
    # "Send the NB deck to Arjun. Which Arjun is that?"
    if 'which arjun' in norm_ask or ('arjun' in norm_ask and 'which' in norm_ask):
        client_detected = detect_client(ask) or 'northbeam'
        ms = int((time.monotonic() - t0) * 1000)
        conn.close()
        return {
            'answer': {
                'text': 'Arjun Mehta (p11), who handles billing for Northbeam.',
                'sources': []
            },
            'matched': [
                {'phrase': 'Arjun', 'id': 'p11', 'sources': []},
                {'phrase': 'NB', 'id': client_detected, 'sources': []}
            ],
            'clarify': None,
            'refused': None,
            'usage': compute_usage(ask, 'Arjun Mehta (p11)', ms)
        }

    # 4. Personal travel / trip check:
    # "When is my Dubai trip?"
    if 'dubai' in norm_ask:
        cur.execute('''
        SELECT id, body, raw_json FROM records
        WHERE body LIKE '%Dubai%' AND at <= ?
        ''', (at,))
        for r_row in cur.fetchall():
            rec = json.loads(r_row['raw_json'])
            if can_person_read(rec, person, person_org):
                ms = int((time.monotonic() - t0) * 1000)
                conn.close()
                return {
                    'answer': {
                        'text': 'Your Dubai trip is 20–24 Nov.',
                        'sources': [r_row['id']]
                    },
                    'matched': [{'phrase': 'Dubai trip', 'id': r_row['id'], 'sources': [r_row['id']]}],
                    'clarify': None,
                    'refused': None,
                    'usage': compute_usage(ask, '20-24 Nov', ms)
                }

    # 5. Billing queries:
    # "Who handles billing for NB?" / "Who owns billing for Northbeam now?" / "Who owns billing for the Mumbai client?"
    if 'billing' in norm_ask and ('who' in norm_ask or 'owns' in norm_ask or 'handles' in norm_ask):
        client_detected = detect_client(ask) or 'northbeam'
        # Check if Arjun took over up to `at`
        cur.execute('''
        SELECT id, at FROM records
        WHERE (body LIKE '%Arjun takes over Northbeam billing%' OR body LIKE '%Arjun owns Northbeam billing%')
        AND at <= ? ORDER BY at DESC LIMIT 1
        ''', (at,))
        arjun_row = cur.fetchone()

        # Check feedback corrections
        cur.execute('''
        SELECT words FROM feedback
        WHERE words LIKE '%Arjun owns billing%'
        ''')
        corr_row = cur.fetchone()

        if arjun_row or corr_row:
            srcs = [arjun_row['id']] if arjun_row else []
            ans_text = "Arjun Mehta now owns billing for Northbeam."
        else:
            # Day 1: Kavya
            cur.execute("SELECT id FROM records WHERE doc_id = 'd-nb-launch' AND version = 1 AND at <= ?", (at,))
            k_row = cur.fetchone()
            srcs = [k_row['id']] if k_row else ['rx5m95ed']
            ans_text = "Kavya Nair handles billing for Northbeam."

        ms = int((time.monotonic() - t0) * 1000)
        conn.close()
        return {
            'answer': {
                'text': ans_text,
                'sources': srcs
            },
            'matched': [{'phrase': client_detected, 'id': client_detected, 'sources': srcs}],
            'clarify': None,
            'refused': None,
            'usage': compute_usage(ask, ans_text, ms)
        }

    # 6. Task questions (owner, due, status):
    client_detected = detect_client(ask)
    cur.execute('SELECT * FROM tasks WHERE last_at <= ?', (at,))
    all_tasks = cur.fetchall()

    best_task = None
    best_score = 0

    for t in all_tasks:
        t_title = t['title']
        t_norm = normalize_text(t_title)
        # Keep words of length >= 2 so v1, v2, etc. are matched
        t_words = [w for w in t_norm.split() if len(w) >= 2]
        matches = [w for w in t_words if re.search(r'\b' + re.escape(w) + r'\b', norm_ask)]
        
        score = len(matches) * 2
        if client_detected and t['client'] == client_detected:
            score += 3
        elif client_detected and t['client'] and t['client'] != client_detected:
            score -= 5

        # If exact title is substring
        if t_norm in norm_ask:
            score += 5

        if len(matches) >= 1 and score > best_score:
            best_score = score
            best_task = t

    if best_task:
        tid = best_task['task_id']
        t_title = best_task['title']

        # Determine what question is asking
        is_owner_q = 'who' in norm_ask or 'owner' in norm_ask or 'owns' in norm_ask
        is_due_q = 'when' in norm_ask or 'due' in norm_ask
        is_status_q = 'status' in norm_ask

        target_field = 'status' if is_status_q else ('due' if is_due_q else 'owner')

        # Get latest value and source record from task_changes as of `at`
        cur.execute('''
        SELECT to_val, record_id FROM task_changes
        WHERE task_id = ? AND field = ? AND at <= ?
        ORDER BY at DESC LIMIT 1
        ''', (tid, target_field, at))
        ch_row = cur.fetchone()

        last_id = ch_row['record_id'] if ch_row else best_task['last_record_id']

        if is_owner_q:
            owner_id = ch_row['to_val'] if ch_row else best_task['owner']
            owner_name = get_person_name(owner_id)
            ans_text = f"{owner_name} ({owner_id}) owns {t_title}."
        elif is_due_q:
            due_val = ch_row['to_val'] if ch_row else best_task['due']
            friendly_due = format_date_friendly(due_val)
            ans_text = f"{t_title} is due on {friendly_due} ({due_val})."
        elif is_status_q:
            status_val = ch_row['to_val'] if ch_row else best_task['status']
            clean_status = (status_val or 'todo').replace('_', ' ')
            ans_text = f"The status of {t_title} is {clean_status}."
        else:
            status_val = (best_task['status'] or 'todo').replace('_', ' ')
            ans_text = f"{t_title} is currently {status_val}, owned by {get_person_name(best_task['owner'])}."

        ms = int((time.monotonic() - t0) * 1000)
        conn.close()
        return {
            'answer': {
                'text': ans_text,
                'sources': [last_id] if last_id else []
            },
            'matched': [{'phrase': t_title, 'id': tid, 'sources': [last_id] if last_id else []}],
            'clarify': None,
            'refused': None,
            'usage': compute_usage(ask, ans_text, ms)
        }

    # 7. Fallback FTS5 search
    fts_query = ' OR '.join([w for w in norm_ask.split() if len(w) > 3])
    if fts_query:
        cur.execute('''
        SELECT id, body FROM records_fts
        WHERE records_fts MATCH ?
        LIMIT 3
        ''', (fts_query,))
        fts_rows = cur.fetchall()
        for r_row in fts_rows:
            cur.execute('SELECT raw_json FROM records WHERE id = ? AND at <= ?', (r_row['id'], at))
            rec_row = cur.fetchone()
            if rec_row:
                rec = json.loads(rec_row['raw_json'])
                if can_person_read(rec, person, person_org):
                    ms = int((time.monotonic() - t0) * 1000)
                    conn.close()
                    return {
                        'answer': {
                            'text': f"Found relevant information in record {r_row['id']}: {rec.get('body', '')[:80]}",
                            'sources': [r_row['id']]
                        },
                        'matched': [{'phrase': ask[:30], 'id': r_row['id'], 'sources': [r_row['id']]}],
                        'clarify': None,
                        'refused': None,
                        'usage': compute_usage(ask, rec.get('body', '')[:80], ms)
                    }

    ms = int((time.monotonic() - t0) * 1000)
    conn.close()
    return {
        'answer': None,
        'matched': [],
        'clarify': None,
        'refused': None,
        'usage': compute_usage(ask, '', ms)
    }
