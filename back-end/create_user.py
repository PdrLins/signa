"""Create a Signa user (needs migration 011 for access levels).

Usage:
    venv/bin/python create_user.py
    venv/bin/python create_user.py --referral K7M2QX9A   # record who invited them

Migration 019: every user gets an account ID (= invite code). With
--referral CODE the new user is linked to the inviter exactly like
POST /auth/register (users.referred_by + a pending referrals row). Before
019 the user is created without an account ID (--referral then fails).
"""

import argparse
import getpass
import sys

from app.core.api_errors import is_missing_schema
from app.core.security import hash_password
from app.db.supabase import get_client
from app.services import referrals


def main():
    parser = argparse.ArgumentParser(description="Create a Signa user")
    parser.add_argument("--referral", metavar="CODE", help="invite code (account ID) of the user who invited them")
    args = parser.parse_args()

    referrer = None
    if args.referral:
        try:
            referrer = referrals.find_referrer(args.referral)
        except Exception as e:
            if is_missing_schema(e):
                print(f"--referral needs migration {referrals.MIGRATION}")
                sys.exit(1)
            raise
        if not referrer:
            print(f"Invite code '{args.referral}' is not valid (unknown or inactive user)")
            sys.exit(1)

    print("=" * 40)
    print(" Signa — Create User")
    print("=" * 40)
    print()

    username = input("Username: ").strip().lower()
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

    telegram_chat_id = input("Telegram Chat ID (optional, Enter to skip): ").strip() or None

    access_level = (input("Access level [free/premium/owner] (default free): ").strip().lower() or "free")
    if access_level not in ("free", "premium", "owner"):
        print("Access level must be free, premium or owner")
        sys.exit(1)

    # Hash password
    password_hash = hash_password(password)

    row = {
        "username": username,
        "password_hash": password_hash,
        "telegram_chat_id": telegram_chat_id,
        "access_level": access_level,
        "is_active": True,
    }
    try:
        row["account_id"] = referrals.unique_account_id()
    except Exception as e:
        if not is_missing_schema(e):
            raise
        print(f"(no account ID: apply migration {referrals.MIGRATION})")
    if referrer:
        row["referred_by"] = referrer["id"]

    # Insert into Supabase
    client = get_client()
    try:
        result = client.table("users").insert(row).execute()

        if result.data:
            user = result.data[0]
            if referrer:
                referrals.add_pending(referrer["id"], str(user["id"]))
            print()
            print(f"User created successfully!")
            print(f"  ID: {user['id']}")
            print(f"  Username: {username}")
            print(f"  Telegram: {telegram_chat_id or '(none: password-only login)'}")
            print(f"  Access level: {access_level}")
            print(f"  Account ID: {user.get('account_id') or '(none before migration 019)'}")
            if referrer:
                print(f"  Invited by: {referrer['username']} (referral pending until their first follow)")
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
