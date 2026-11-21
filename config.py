"""Configuration and domain constants for MemoFlow."""
import os, json
from datetime import timedelta

PACK_ROOT = os.environ.get('R3_PACK') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.path.join(PACK_ROOT, 'data')
DB_PATH = os.environ.get('MEMOFLOW_DB') or os.path.join(os.path.dirname(__file__), 'memoflow.db')

ZONES = {
    'Asia/Kolkata': timedelta(hours=5, minutes=30),
    'Europe/London': timedelta(0),
    'UTC': timedelta(0)
}

CLIENT_ALIASES = {
    'northbeam': ['northbeam', 'nb', 'nb retail', 'mumbai client', 'mumbai'],
    'cobaltline': ['cobaltline', 'cobalt', 'cl', 'london account', 'london'],
    'alderpoint': ['alderpoint', 'ap']
}

ALIAS_TO_CLIENT = {}
for cid, aliases in CLIENT_ALIASES.items():
    for al in aliases:
        ALIAS_TO_CLIENT[al.lower()] = cid

def load_people():
    p_path = os.path.join(DATA_DIR, 'people.json')
    if not os.path.isfile(p_path):
        return {}, {}
    data = json.load(open(p_path, encoding='utf-8'))
    people_by_id = {}
    people_by_name = {}
    for org_id, org_data in data.items():
        for p in org_data.get('people', []):
            p['org'] = org_id
            people_by_id[p['id']] = p
            people_by_name[p['name'].lower()] = p
    return people_by_id, people_by_name

PEOPLE_BY_ID, PEOPLE_BY_NAME = load_people()

def get_person_zone(person_id):
    p = PEOPLE_BY_ID.get(person_id)
    if p:
        return p.get('zone', 'Asia/Kolkata')
    return 'Asia/Kolkata'

def get_person_org(person_id):
    p = PEOPLE_BY_ID.get(person_id)
    if p:
        return p.get('org', 'org_kp')
    return 'org_kp'
