"""
Main entry point — fetches thesis portfolio data, watchlist data, and sends the email.
Run directly or via Windows Task Scheduler.

Usage:
  python main.py --dry-run              # saves HTML to preview.html for user 'admin'
  python main.py --username alice       # sends email for user 'alice'
"""

import sys
from datetime import datetime

from database import get_conn, init_db
from portfolio import get_all_thesis_data
from watchlist_manager import get_watchlist_data
from email_sender import build_html, send_email


def run(user_id: int, dry_run: bool = False) -> None:
    print(f"[main] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print("[main] Fetching thesis portfolio data...")
    theses = get_all_thesis_data(user_id)

    print("[main] Fetching watchlist data...")
    watchlist_data = get_watchlist_data(user_id)

    html = build_html(theses, watchlist_data)

    if dry_run:
        out_path = "preview.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[main] Dry run — saved to {out_path}")
        return

    print("[main] Sending email...")
    success = send_email(html)
    if success:
        print("[main] Done.")
    else:
        print("[main] Email failed — check .env settings.")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Investment thesis tracker newsletter")
    parser.add_argument("--dry-run", action="store_true",
                        help="Save HTML to preview.html instead of emailing")
    parser.add_argument("--username", default="admin",
                        help="Username to generate the report for (default: admin)")
    args = parser.parse_args()

    init_db()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username=?", (args.username,)
        ).fetchone()

    if not row:
        print(f"[main] User '{args.username}' not found in the database.")
        sys.exit(1)

    run(user_id=row["id"], dry_run=args.dry_run)
