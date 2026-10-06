"""Assign an SH-205 role to a Firebase user (SH.docx §12).

Usage (from backend/):

    .venv/Scripts/python.exe scripts/set_role.py you@example.com admin

Roles: admin | dispatcher | driver | customer

THIS WRITES TO THE LIVE FIREBASE PROJECT: it sets a custom claim on an
existing user. It does not create users — create them first in the Firebase
console (Authentication -> Users -> Add user).

The user must sign in again (or refresh their token) before the new role
appears in their ID token.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROLES = {"admin", "dispatcher", "driver", "customer"}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2].lower() not in ROLES:
        raise SystemExit(f"usage: set_role.py <email> <{'|'.join(sorted(ROLES))}>")

    email, role = sys.argv[1], sys.argv[2].lower()

    from firebase_admin import auth

    from app.core.security import init_firebase, set_user_role

    if not init_firebase():
        raise SystemExit("Firebase Admin could not initialise; check credentials.")

    from app.core import security

    try:
        user = auth.get_user_by_email(email, app=security._firebase_app)
    except auth.UserNotFoundError:
        raise SystemExit(
            f"No Firebase user with email {email}. Create it in the Firebase "
            "console first (Authentication -> Users -> Add user)."
        ) from None

    result = set_user_role(user.uid, role)
    print(f"OK: {email} (uid {user.uid}) now has role {result['role']}.")
    print("They must sign in again for the role to appear in their token.")


if __name__ == "__main__":
    main()
