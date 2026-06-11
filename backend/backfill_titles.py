"""
backfill_titles.py — one-time re-title of existing chat sessions.
================================================================
Sessions historically took their title from the FIRST message, so any chat
opened with "hi" is permanently titled "hi" and is indistinguishable in the
sidebar. This re-titles each session to its first SUBSTANTIVE (non-greeting)
user message — the same rule new chats now use.

Usage (from backend/):
    python backfill_titles.py            # DRY RUN — shows changes, writes nothing
    python backfill_titles.py --apply    # actually writes the new titles

Safe to re-run: sessions already correctly titled (or that contain only
greetings) are left untouched.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from database.models import ChatMessage
from services.ai_router import _is_titleable, _title_from


def main(apply: bool = False) -> int:
    db = SessionLocal()
    try:
        rows = db.query(ChatMessage).order_by(ChatMessage.id.asc()).all()

        # Group rows per (business_id, session_id), preserving insertion order.
        sessions = {}
        for r in rows:
            if not r.session_id:
                continue
            sessions.setdefault((r.business_id, r.session_id), []).append(r)

        changes = []
        for (biz, sid), msgs in sessions.items():
            current = msgs[0].session_title or ""

            new_title = None
            for m in msgs:
                if m.role == "user" and _is_titleable(m.content):
                    new_title = _title_from(m.content)
                    break

            if not new_title or new_title == current:
                continue  # only greetings, or already correct → leave as-is

            changes.append((biz, sid, current, new_title, len(msgs)))
            if apply:
                for m in msgs:
                    m.session_title = new_title

        if apply:
            db.commit()

        verb = "re-titled" if apply else "would be re-titled"
        print(f"{'APPLIED' if apply else 'DRY RUN'} — {len(changes)} session(s) {verb}:\n")
        for biz, sid, old, new, n in changes:
            print(f"  user={biz} [{sid[:8]}] {n:>3} msgs: '{old[:30]}'  ->  '{new[:40]}'")
        if not apply and changes:
            print("\nRun again with --apply to write these changes.")
        elif not changes:
            print("  (nothing to change)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
