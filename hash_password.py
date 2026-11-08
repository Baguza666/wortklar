#!/usr/bin/env python3
"""
Password Hash Generator for Wortklar.
Generates a secure scrypt password hash to use in Render's WORTKLAR_PASSWORD_HASH environment variable.

Usage:
    python3 hash_password.py
    # or pass directly:
    python3 hash_password.py "your-secure-password"
"""

import getpass
import sys
from wortklar.auth import hash_password

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pwd = sys.argv[1]
    else:
        pwd = getpass.getpass("Enter password for Wortklar single-owner access: ")
        pwd_confirm = getpass.getpass("Confirm password: ")
        if pwd != pwd_confirm:
            print("Error: Passwords did not match.", file=sys.stderr)
            sys.exit(1)

    if not pwd:
        print("Error: Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    hashed = hash_password(pwd)
    print("\n" + "=" * 70)
    print(" Wortklar Password Hash Generated")
    print("=" * 70)
    print("Set this environment variable in Render (under Environment Variables):")
    print("\nKey:   WORTKLAR_PASSWORD_HASH")
    print(f"Value: {hashed}")
    print("=" * 70)

