"""Metadata and permission filtering for MemoFlow."""
import json
import re


def _forget_terms(forgets):
    """Extract the subject of a natural-language forget request."""
    terms = []
    for value in forgets or []:
        text = (value or "").strip()
        text = re.sub(r"^forget\s+(?:what\s+i\s+said\s+about\s+)?", "", text, flags=re.I)
        text = re.sub(r"^please\s+forget\s+", "", text, flags=re.I)
        text = text.strip(" .!?\"'")
        if text:
            terms.append(text.casefold())
    return terms


def can_person_read(rec, person_id, person_org, forgets=None):
    """Apply organization, visibility and person-specific forget rules."""
    if not person_org or rec.get("org") != person_org:
        return False

    # Fail closed: absent, malformed, or unknown visibility must never become team-readable.
    visibility = rec.get("visibility")
    if not isinstance(visibility, str):
        return False
    visibility = visibility.strip().casefold()
    if visibility == "private":
        if rec.get("author") != person_id:
            return False
    elif visibility == "restricted":
        readers = rec.get("readers") or []
        if isinstance(readers, str):
            try:
                readers = json.loads(readers)
            except (TypeError, ValueError):
                return False
        # Malformed reader metadata must never grant access by substring/key matching.
        if not isinstance(readers, list) or not all(isinstance(item, str) for item in readers):
            return False
        if str(person_id) not in readers:
            return False
    elif visibility != "team":
        return False

    if forgets:
        searchable = " ".join((
            rec.get("body") or "",
            rec.get("title") or "",
            rec.get("subject") or ""
        )).casefold()
        if any(term in searchable for term in _forget_terms(forgets)):
            return False
    return True


def is_newsletter_or_spam(rec):
    """Heuristic suppression for obvious subscription mail; not question intent."""
    author = (rec.get("author") or "").casefold()
    subject = (rec.get("subject") or "").casefold()
    body = (rec.get("body") or "").casefold()
    if author.startswith("ext:news@") or "producthunt" in author:
        return True
    return "unsubscribe" in body or "weekly digest" in subject or "newsletter" in subject


def filter_records_for_person(records, person_id, person_org, client=None,
                               skip_newsletters=False, forgets=None):
    """Apply authorization and optional client/newsletter filters."""
    out = []
    for record in records:
        if not can_person_read(record, person_id, person_org, forgets=forgets):
            continue
        if client and record.get("client") and record.get("client") != client:
            continue
        if skip_newsletters and is_newsletter_or_spam(record):
            continue
        out.append(record)
    return out
