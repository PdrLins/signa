"""Show Signa usernames and set a new password — for when you forget either.

Usage:
    venv/bin/python reset_password.py
"""

import getpass
import sys

from app.core.security import hash_password
from app.db.supabase import get_client


def main():
    client = get_client()
    users = client.table("users").select("id, username, is_active").order("created_at").execute().data or []
    if not users:
        print("No users found — create one with: venv/bin/python create_user.py")
        sys.exit(1)

    print("Users:")
    for i, u in enumerate(users, 1):
        print(f"  {i}. {u['username']}{'' if u.get('is_active') else '  (inactive)'}")

    if len(users) == 1:
        user = users[0]
    else:
        choice = input("Number of the user to reset: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(users):
            print("Invalid choice")
            sys.exit(1)
        user = users[int(choice) - 1]

    print(f"\nSetting a new password for '{user['username']}'")
    password = getpass.getpass("New password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters")
        sys.exit(1)
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match")
        sys.exit(1)

    client.table("users").update({
        "password_hash": hash_password(password),
        "login_attempts": 0,
        "locked_until": None,
    }).eq("id", user["id"]).execute()
    print(f"Password updated. Log in as '{user['username']}' (lowercase).")


if __name__ == "__main__":
    main()
