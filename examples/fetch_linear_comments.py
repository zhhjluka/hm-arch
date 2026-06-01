"""Fetch comments for a Linear issue using LINEAR_API_KEY."""

from __future__ import annotations

import sys

from hm_arch import fetch_linear_issue_comments


def main() -> None:
    issue_id = sys.argv[1] if len(sys.argv) > 1 else "MEM-6"
    for comment in fetch_linear_issue_comments(issue_id):
        author = comment.user_name or "Unknown"
        print(f"{author}: {comment.body}")


if __name__ == "__main__":
    main()
