"""Metadata and permission filtering for MemoFlow."""
import json, re

def can_person_read(rec, person_id, person_org, forgets=None):
    """Strict privacy and permission filter:
    1. Organization check (never leak rival org_bw).
    2. Visibility check:
       - 'team': anyone in person_org can see.
       - 'private': only original author can see.
       - 'restricted': only people in readers list can see.
    3. Forget check: if person requested to forget a phrase present in this record, hide it.
    """
    # 1. Org check
    if rec.get('org') != person_org:
        return False

    # 2. Visibility check
    vis = rec.get('visibility', 'team')
    if vis == 'team':
        pass
    elif vis == 'private':
        if rec.get('author') != person_id:
            return False
    elif vis == 'restricted':
        readers = rec.get('readers') or []
        if isinstance(readers, str):
            try:
                readers = json.loads(readers)
            except Exception:
                readers = [readers]
        if person_id not in readers:
            return False
    else:
        return False

    # 3. Forget filter
    if forgets:
        text = ((rec.get('body') or '') + ' ' + (rec.get('title') or '') + ' ' + (rec.get('subject') or '')).lower()
        for f in forgets:
            if f.lower() in text:
                return False

    return True

def is_newsletter_or_spam(rec):
    """Detect external newsletters or subscriptions that may be skipped via user preference."""
    author = (rec.get('author') or '').lower()
    subject = (rec.get('subject') or '').lower()
    body = (rec.get('body') or '').lower()

    if author.startswith('ext:news@') or 'producthunt' in author or 'weekly' in author or 'newsletter' in author:
        return True
    if 'unsubscribe' in body or 'weekly digest' in subject or 'newsletter' in subject:
        return True
    return False

def filter_records_for_person(records, person_id, person_org, client=None, skip_newsletters=False, forgets=None):
    """Filter candidate records applying all permission, client, and preference rules."""
    out = []
    for r in records:
        if not can_person_read(r, person_id, person_org, forgets=forgets):
            continue
        if client and r.get('client') and r.get('client') != client:
            continue
        if skip_newsletters and is_newsletter_or_spam(r):
            continue
        out.append(r)
    return out

