"""Create a Signa user — run once to set up your account.

Usage:
    venv/bin/python create_user.py
"""

import getpass
import sys

from app.core.security import hash_password
from app.db.supabase import get_client


def main():
    print("=" * 40)
    print(" Signa — Create User")
    print("=" * 40)
    print()

    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match")
        sys.exit(1)

    telegram_chat_id = input("Telegram Chat ID: ").strip()
    if not telegram_chat_id:
        print("Telegram Chat ID is required for OTP login")
        sys.exit(1)

    # Hash password
    password_hash = hash_password(password)

    # Insert into Supabase
    client = get_client()
    try:
        result = client.table("users").insert({
            "username": username,
            "password_hash": password_hash,
            "telegram_chat_id": telegram_chat_id,
            "is_active": True,
        }).execute()

        if result.data:
            user = result.data[0]
            print()
            print(f"User created successfully!")
            print(f"  ID: {user['id']}")
            print(f"  Username: {username}")
            print(f"  Telegram: {telegram_chat_id}")
            print()
            print("You can now login at POST /api/v1/auth/login")
        else:
            print("Failed to create user — no data returned")
            sys.exit(1)

    except Exception as e:
        if "duplicate key" in str(e).lower():
            print(f"User '{username}' already exists")
        else:
            print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
