"""hustle-on CLI — thin wrapper over hustleon_core (kept for backward compat).

Usage:
  python hustleon.py                # hold indefinitely (enforces lid/sleep settings)
  python hustleon.py --timer 60     # hold 60 min then release
  python hustleon.py --until 18:00  # hold until 18:00 (tomorrow if passed)
  python hustleon.py --check        # show current lid/sleep settings
"""
from hustleon_core import main

if __name__ == "__main__":
    raise SystemExit(main())
