"""Matching accuracy on 36 client-style rewordings. Run: uv run python analysis/matching_eval.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import match  # noqa: E402
from app.match_eval import CASES, run  # noqa: E402

if __name__ == "__main__":
    print(f"Matcher in use: {match.method()}")
    for k, v in run().items():
        print(f"  {k}: {v:.0%}")
