"""Sign in to Firebase and print an ID token for testing the API by hand.

Usage (from backend/):

    .venv/Scripts/python.exe scripts/get_id_token.py you@example.com

The password is prompted for and never echoed. The Firebase *web* API key is
read from frontend/.env (VITE_FIREBASE_API_KEY) and never printed.

Requires the Email/Password sign-in provider to be enabled in the Firebase
console (Authentication -> Sign-in method). This script only signs in; it
does not create users or change anything in the project.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

FRONTEND_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}"
)


def read_api_key() -> str:
    for line in FRONTEND_ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("VITE_FIREBASE_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"VITE_FIREBASE_API_KEY not found in {FRONTEND_ENV}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: get_id_token.py <email>")

    email = sys.argv[1]
    password = getpass.getpass(f"Password for {email}: ")

    request = urllib.request.Request(
        SIGN_IN_URL.format(key=read_api_key()),
        data=json.dumps(
            {"email": email, "password": password, "returnSecureToken": True}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        message = json.loads(exc.read()).get("error", {}).get("message", exc.reason)
        raise SystemExit(f"Sign-in failed: {message}") from None

    print(body["idToken"])
    print(
        "\n# Valid for ~1 hour. Use as:  -H \"Authorization: Bearer <token>\"",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
