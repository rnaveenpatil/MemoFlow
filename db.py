"""Database management with SQLite and SQLite FTS5 for MemoFlow."""
import sqlite3, json, os, re
from datetime import datetime, timedelta
from MemoFlow.config import DB_PATH, ZONES, get_person_zone

def get_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(reset=False, db_path=None):
    path = db_path or DB_PATH
    if reset and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    conn = get_connection(path)
    cur = conn.cursor()

    cur.execute('''
    CREATE TABLE IF NOT EXISTS records (
        id TEXT PRIMARY KEY,
        day INTEGER,
        org TEXT,
        type TEXT,
        at TEXT,
        author TEXT,
        client TEXT,
        visibility TEXT,
        readers TEXT,
        task_id TEXT,
        doc_id TEXT,
        version INTEGER,
        title TEXT,
        owner TEXT,
        due TEXT,
        status TEXT,
        change_field TEXT,
        change_from TEXT,
        change_to TEXT,
        channel TEXT,
        subject TEXT,
        body TEXT,
        raw_json TEXT
    );
    ''')

    cur.execute('''
    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
        id,
        title,
        body,
        author,
        client,
        subject,
        channel
    );
    ''')

    cur.execute("""
    CREATE TABLE IF NOT EXISTS people (
        person_id TEXT PRIMARY KEY,
        org TEXT,
        name TEXT NOT NULL,
        role TEXT,
        zone TEXT,
        raw_json TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        raw_json TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS workspace_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        title TEXT,
        client TEXT,
        owner TEXT,
        due TEXT,
        status TEXT,
        last_record_id TEXT,
        last_day INTEGER,
        last_at TEXT
    );
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS task_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        title TEXT,
        client TEXT,
        field TEXT,
        from_val TEXT,
        to_val TEXT,
        record_id TEXT,
        day INTEGER,
        at TEXT
    );
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS meetings (
        event_id TEXT PRIMARY KEY,
        client TEXT,
        title TEXT,
        start_utc TEXT,
        attendees TEXT,
        author TEXT,
        record_id TEXT,
        day INTEGER
    );
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day INTEGER,
        person TEXT,
        type TEXT,
        words TEXT,
        meeting TEXT,
        topic TEXT,
        verdict TEXT
    );
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS forgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person TEXT,
        what TEXT
    );
    ''')
    feedback_columns = {row["name"] for row in cur.execute("PRAGMA table_info(feedback)")}
    if "available_day" not in feedback_columns:
        cur.execute("ALTER TABLE feedback ADD COLUMN available_day INTEGER")
        cur.execute("UPDATE feedback SET available_day = COALESCE(day, 0) + 1")
    # Migrate older databases so forget rules obey the same replay-day boundary.
    forget_columns = {row["name"] for row in cur.execute("PRAGMA table_info(forgets)")}
    if "day" not in forget_columns:
        cur.execute("ALTER TABLE forgets ADD COLUMN day INTEGER")

    cur.execute('''
    CREATE TABLE IF NOT EXISTS promises (
        record_id TEXT PRIMARY KEY,
        client TEXT,
        owner TEXT,
        what TEXT,
        due TEXT,
        day INTEGER,
        at TEXT,
        fulfilled INTEGER DEFAULT 0,
        fulfilled_day INTEGER
    );
    ''')
    promise_columns = {row["name"] for row in cur.execute("PRAGMA table_info(promises)")}
    if "fulfilled_day" not in promise_columns:
        cur.execute("ALTER TABLE promises ADD COLUMN fulfilled_day INTEGER")

    conn.commit()
    conn.close()

def sync_workspace_metadata(conn, data_dir=None):
    """Persist people and client directories from the selected workspace pack."""
    from MemoFlow.config import DATA_DIR, PEOPLE_BY_ID, CLIENTS
    data_dir = data_dir or DATA_DIR
    people_path = os.path.join(data_dir, "people.json")
    clients_path = os.path.join(data_dir, "clients.json")

    if os.path.isfile(people_path):
        with open(people_path, encoding="utf-8") as handle:
            raw_people = json.load(handle)
        if isinstance(raw_people, list):
            groups = [("default", raw_people)]
        elif isinstance(raw_people, dict) and isinstance(raw_people.get("people"), list):
            groups = [(raw_people.get("org") or raw_people.get("id") or "default",
                       raw_people["people"])]
        elif isinstance(raw_people, dict):
            groups = list(raw_people.items())
        else:
            raise ValueError("people.json must be a list or organization mapping")

        normalized_people = []
        for org_id, group in groups:
            members = group if isinstance(group, list) else group.get("people", [])
            for item in members:
                if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                    continue
                person = dict(item)
                person["org"] = person.get("org") or org_id
                normalized_people.append(person)

        conn.execute("DELETE FROM people")
        for person in normalized_people:
            conn.execute(
                """INSERT OR REPLACE INTO people
                   (person_id, org, name, role, zone, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(person["id"]), person.get("org"), person.get("name", ""),
                 person.get("role"), person.get("zone"), json.dumps(person, ensure_ascii=False))
            )
        conn.execute(
            """INSERT OR REPLACE INTO workspace_metadata(key,value)
               VALUES ('people_source', ?)""", (os.path.abspath(people_path),)
        )

    if os.path.isfile(clients_path):
        with open(clients_path, encoding="utf-8") as handle:
            raw_clients = json.load(handle)
        if isinstance(raw_clients, dict):
            raw_clients = raw_clients.get("clients", [])
        if not isinstance(raw_clients, list):
            raise ValueError("clients.json must contain a list")
        conn.execute("DELETE FROM clients")
        for client in raw_clients:
            if not isinstance(client, dict) or not client.get("id"):
                continue
            conn.execute(
                """INSERT OR REPLACE INTO clients(client_id,name,raw_json)
                   VALUES (?,?,?)""",
                (str(client["id"]), str(client.get("name") or client["id"]),
                 json.dumps(client, ensure_ascii=False))
            )
        conn.execute(
            """INSERT OR REPLACE INTO workspace_metadata(key,value)
               VALUES ('clients_source', ?)""", (os.path.abspath(clients_path),)
        )
    conn.commit()



def parse_promise_from_record(r, day):
    # Detect commitments in chats/mails
    # e.g., "the checkout copy kal tak bhej dunga"
    # "Will share the API spec for the TMS feed by EOD today."
    # "the returns page copy next Monday tak share kar dungi/dunga, pakka."
    body = (r.get('body') or '') + ' ' + (r.get('subject') or '')
    author = r.get('author')
    client = r.get('client')
    at_str = r.get('at', '')
    rec_id = r.get('id')

    if not body or not author or not client:
        return None

    # Calculate record date
    rec_dt = None
    try:
        rec_dt = datetime.strptime(at_str[:19], '%Y-%m-%dT%H:%M:%S')
        # Relative promises such as "tomorrow" are interpreted in the author's time zone.
        rec_dt += ZONES.get(get_person_zone(author), ZONES['UTC'])
    except (TypeError, ValueError):
        pass

    what = None
    due = None

    # Pattern 1: "... kal tak bhej dunga" or "... kal tak"
    m1 = re.search(r'(the [^,.\n]+?)\s+kal tak', body, re.I)
    if m1 and rec_dt:
        what = m1.group(1).strip()
        due = (rec_dt + timedelta(days=1)).strftime('%Y-%m-%d')

    # Pattern 2: "by EOD today" or "by Thursday"
    if not what:
        m2 = re.search(r'Will share (the [^,.\n]+?)\s+by EOD today', body, re.I)
        if m2 and rec_dt:
            what = m2.group(1).strip()
            due = rec_dt.strftime('%Y-%m-%d')

    # Pattern 3: "... next Monday tak"
    if not what:
        m3 = re.search(r'(the [^,.\n]+?)\s+next Monday tak', body, re.I)
        if m3 and rec_dt:
            what = m3.group(1).strip()
            # Find next monday
            days_ahead = 7 - rec_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            due = (rec_dt + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

    # Pattern 4: "I will send ... by Thursday"
    if not what:
        m4 = re.search(r'I will send (the [^,.\n]+?)\s+by Thursday', body, re.I)
        if m4 and rec_dt:
            what = m4.group(1).strip()
            # Thursday in the same week
            thurs_offset = 3 - rec_dt.weekday()
            if thurs_offset < 0:
                thurs_offset += 7
            due = (rec_dt + timedelta(days=thurs_offset)).strftime('%Y-%m-%d')

    if what and due:
        return {
            'record_id': rec_id,
            'client': client,
            'owner': author,
            'what': what,
            'due': due,
            'day': day,
            'at': at_str
        }
    return None

def insert_record(conn, r, day):
    cur = conn.cursor()
    change = r.get('change') or {}
    readers_json = json.dumps(r.get('readers')) if r.get('readers') else None
    
    cur.execute('''
    INSERT OR REPLACE INTO records (
        id, day, org, type, at, author, client, visibility, readers,
        task_id, doc_id, version, title, owner, due, status,
        change_field, change_from, change_to, channel, subject, body, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        r.get('id'),
        day,
        r.get('org'),
        r.get('type'),
        r.get('at'),
        r.get('author'),
        r.get('client'),
        r.get('visibility', 'team'),
        readers_json,
        r.get('task_id'),
        r.get('doc_id'),
        r.get('version'),
        r.get('title'),
        r.get('owner'),
        r.get('due'),
        r.get('status'),
        change.get('field'),
        change.get('from'),
        change.get('to'),
        r.get('channel'),
        r.get('subject'),
        r.get('body'),
        json.dumps(r)
    ))

    # Keep the full-text index idempotent when a day is re-ingested.
    cur.execute('DELETE FROM records_fts WHERE id = ?', (r.get('id'),))

    # Insert into FTS5
    cur.execute('''
    INSERT INTO records_fts (id, title, body, author, client, subject, channel)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        r.get('id'),
        r.get('title') or '',
        r.get('body') or '',
        r.get('author') or '',
        r.get('client') or '',
        r.get('subject') or '',
        r.get('channel') or ''
    ))

    # Track tasks
    if r.get('type') == 'task' and r.get('task_id'):
        tid = r['task_id']
        cur.execute('SELECT * FROM tasks WHERE task_id = ?', (tid,))
        existing = cur.fetchone()
        c_field = change.get('field')

        if existing:
            cur_title = r.get('title') or existing['title']
            cur_client = r.get('client') or existing['client']
            cur_owner = r.get('owner') or existing['owner']
            cur_due = r.get('due') or existing['due']
            cur_status = r.get('status') or existing['status']
            last_rec = r.get('id') if c_field in ('status', 'owner', 'due', 'created') else existing['last_record_id']
        else:
            cur_title = r.get('title') or ''
            cur_client = r.get('client') or ''
            cur_owner = r.get('owner') or ''
            cur_due = r.get('due') or ''
            cur_status = r.get('status') or 'todo'
            last_rec = r.get('id')

        cur.execute('''
        INSERT OR REPLACE INTO tasks (
            task_id, title, client, owner, due, status, last_record_id, last_day, last_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tid,
            cur_title,
            cur_client,
            cur_owner,
            cur_due,
            cur_status,
            last_rec,
            day,
            r.get('at')
        ))

        # Log change only when real change occurred (both from and to exist)
        if c_field in ('status', 'owner', 'due') and change.get('to') and change.get('from'):
            cur.execute('''
            INSERT INTO task_changes (task_id, title, client, field, from_val, to_val, record_id, day, at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tid,
                cur_title,
                cur_client,
                c_field,
                change.get('from'),
                change.get('to'),
                r.get('id'),
                day,
                r.get('at')
            ))

    # Track meetings
    if r.get('type') == 'event' and r.get('event_id'):
        cur.execute('''
        INSERT OR REPLACE INTO meetings (
            event_id, client, title, start_utc, attendees, author, record_id, day
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            r.get('event_id'),
            r.get('client'),
            r.get('title'),
            r.get('start'),
            json.dumps(r.get('attendees') or []),
            r.get('author'),
            r.get('id'),
            day
        ))

    # Check for promises
    p_info = parse_promise_from_record(r, day)
    if p_info:
        cur.execute('''
        INSERT OR REPLACE INTO promises (record_id, client, owner, what, due, day, at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            p_info['record_id'],
            p_info['client'],
            p_info['owner'],
            p_info['what'],
            p_info['due'],
            p_info['day'],
            p_info['at']
        ))

    # Check for promise fulfillment / delivery
    # e.g. "Sharing the UTM sheet as promised" or "delivered the revised banner set"
    body = (r.get('body') or '') + ' ' + (r.get('subject') or '')
    if 'as promised' in body.lower() or 'delivered' in body.lower():
        cur.execute('SELECT record_id, what FROM promises WHERE client = ? AND fulfilled = 0', (r.get('client'),))
        for prom in cur.fetchall():
            what_kw = prom['what'].replace('the ', '').strip().lower()
            if what_kw in body.lower():
                cur.execute('UPDATE promises SET fulfilled = 1, fulfilled_day = ? WHERE record_id = ?', (day, prom['record_id']))
