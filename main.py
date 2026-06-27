"""
Main entry point — fetches thesis portfolio data, watchlist data, and sends the email.
Run directly or via Windows Task Scheduler.
"""

import sys
from datetime import datetime

from portfolio import get_all_thesis_data
from watchlist_manager import get_watchlist_data
from email_sender import build_html, send_email


def run(dry_run: bool = False) -> None:
    print(f"[main] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print("[main] Fetching thesis portfolio data...")
    theses = get_all_thesis_data()

    print("[main] Fetching watchlist data...")
    watchlist_data = get_watchlist_data()

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
    args = parser.parse_args()

    run(dry_run=args.dry_run)
