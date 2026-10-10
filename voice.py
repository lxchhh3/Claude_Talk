"""Launcher for the `voice` command: python voice.py [list|play|set|show|say] ..."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_talk.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
