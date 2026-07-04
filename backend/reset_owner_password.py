"""
reset_owner_password.py — reset a LOCAL owner account's password.

Usage (from backend/, with the venv active and the dev server STOPPED):
    python reset_owner_password.py <username> <new_password>

Example:
    python reset_owner_password.py Rakshith MyNewPass123

Only touches the `password` column of that one user in the local SQLite DB.
No other data is read or changed.
"""
import sys
from database.db import SessionLocal
from database.models import User
from services.auth import hash_password

if len(sys.argv) != 3:
    print(__doc__); sys.exit(1)

username, new_password = sys.argv[1], sys.argv[2]
db = SessionLocal()
try:
    u = db.query(User).filter(User.username == username).first()
    if not u:
        print(f"No local user named '{username}'. Existing owners:")
        for o in db.query(User).filter(User.parent_business_id.is_(None)).all():
            print(f"  - {o.username}  (business: {o.business_name})")
        sys.exit(2)
    u.password = hash_password(new_password)
    db.commit()
    print(f"OK — password reset for '{u.username}' (business: {u.business_name}). You can log in now.")
finally:
    db.close()
