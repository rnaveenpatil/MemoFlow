"""Configuration and dataset discovery for MemoFlow."""
import json
import os
from datetime import timedelta

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _has_dataset(root):
    return bool(root and os.path.isfile(os.path.join(root, "data", "people.json"))
                and os.path.isdir(os.path.join(root, "data", "days")))


def _resolve_pack_root():
    configured = os.environ.get("R3_PACK")
    if configured and _has_dataset(configured):
        return os.path.abspath(configured)
    cwd = os.path.abspath(os.getcwd())
    if _has_dataset(cwd):
        return cwd
    # This repository keeps the supplied challenge pack under dataset/.
    if _has_dataset(os.path.join(MODULE_DIR, "dataset")):
        return os.path.join(MODULE_DIR, "dataset")
    parent = os.path.abspath(os.path.join(MODULE_DIR, ".."))
    if _has_dataset(parent):
        return parent
    # Preserve the conventional challenge-pack layout when data is mounted later.
    return os.path.abspath(configured or cwd)


PACK_ROOT = _resolve_pack_root()
DATA_DIR = os.path.join(PACK_ROOT, "data")
DB_PATH = os.environ.get("MEMOFLOW_DB") or os.path.join(MODULE_DIR, "memoflow.db")


def load_dotenv():
    candidates = [os.path.join(MODULE_DIR, ".env"), os.path.join(PACK_ROOT, ".env")]
    for env_path in candidates:
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key.strip(), value)
        except OSError:
            continue


load_dotenv()

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "qwen3.8-27b")
LLM_API_KEY = (os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
               or os.environ.get("OPENAI_API_KEY"))

# Dataset zones are IANA names. These offsets cover the challenge's listed zones.
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
    for org_id, org_data in data.items():
        for original in org_data.get("people", []):
            person = dict(original)
            person["org"] = org_id
            by_id[person["id"]] = person
            by_name.setdefault(person["name"].casefold(), person)
    return by_id, by_name


def load_clients():
    path = os.path.join(DATA_DIR, "clients.json")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


PEOPLE_BY_ID, PEOPLE_BY_NAME = _load_people()
CLIENTS = load_clients()


def get_person_zone(person_id):
    return PEOPLE_BY_ID.get(person_id, {}).get("zone", "UTC")


def get_person_org(person_id):
    return PEOPLE_BY_ID.get(person_id, {}).get("org")
