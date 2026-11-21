"""Workspace and dataset configuration for MemoFlow."""
import json
import os
from datetime import timedelta

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _candidate_roots():
    roots = []
    configured = os.environ.get("R3_PACK")
    if configured:
        roots.append(os.path.abspath(configured))
    current = os.path.abspath(os.getcwd())
    module = MODULE_DIR
    for start in (current, module):
        path = start
        for _ in range(6):
            if path not in roots:
                roots.append(path)
            path = os.path.dirname(path)
    # Common challenge-pack layouts.
    for root in list(roots):
        for child in ("dataset", "BuildSprint-R3-candidate", "R3", "challenge"):
            candidate = os.path.join(root, child)
            if candidate not in roots:
                roots.append(candidate)
    return roots


def _find_data_dir():
    explicit = os.environ.get("MEMOFLOW_DATA_DIR")
    if explicit:
        path = os.path.abspath(explicit)
        if os.path.isfile(os.path.join(path, "people.json")):
            return path

    for root in _candidate_roots():
        # Both pack-root/data and direct data-directory layouts are supported.
        for candidate in (os.path.join(root, "data"), root):
            if os.path.isfile(os.path.join(candidate, "people.json")):
                return os.path.abspath(candidate)
    return os.path.join(MODULE_DIR, "data")


DATA_DIR = _find_data_dir()
PACK_ROOT = os.path.dirname(DATA_DIR) if os.path.basename(DATA_DIR).casefold() == "data" else DATA_DIR
DB_PATH = os.environ.get("MEMOFLOW_DB") or os.path.join(MODULE_DIR, "memoflow.db")


def load_dotenv():
    for env_path in (os.path.join(MODULE_DIR, ".env"), os.path.join(PACK_ROOT, ".env")):
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        except OSError:
            continue


load_dotenv()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "qwen3.8-27b")
LLM_API_KEY = (os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
               or os.environ.get("OPENAI_API_KEY"))

ZONES = {
    "Asia/Kolkata": timedelta(hours=5, minutes=30),
    "Europe/London": timedelta(0),
    "UTC": timedelta(0),
}


def _load_people():
    path = os.path.join(DATA_DIR, "people.json")
    if not os.path.isfile(path):
        return {}, {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    by_id, by_name = {}, {}
    if isinstance(data, list):
        groups = [("default", {"people": data})]
    elif isinstance(data, dict) and isinstance(data.get("people"), list):
        groups = [(data.get("org") or data.get("id") or "default", data)]
    elif isinstance(data, dict):
        groups = list(data.items())
    else:
        raise ValueError("people.json must contain a list or an organization-to-people mapping")

    for org_id, org_data in groups:
        members = org_data if isinstance(org_data, list) else org_data.get("people", [])
        for original in members:
            if not isinstance(original, dict) or not original.get("id") or not original.get("name"):
                continue
            person = dict(original)
            person["org"] = person.get("org") or org_id
            by_id[str(person["id"])] = person
            by_name.setdefault(person["name"].casefold(), person)
    return by_id, by_name


def load_clients():
    path = os.path.join(DATA_DIR, "clients.json")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("clients", [])
    return data if isinstance(data, list) else []


PEOPLE_BY_ID, PEOPLE_BY_NAME = _load_people()
CLIENTS = load_clients()


def get_person_zone(person_id):
    return PEOPLE_BY_ID.get(str(person_id), {}).get("zone", "UTC")


def get_person_org(person_id):
    return PEOPLE_BY_ID.get(str(person_id), {}).get("org")
