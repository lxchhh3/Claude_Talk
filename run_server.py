"""Launcher registered with Claude Code: `python run_server.py` (stdio MCP)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_talk.server import main  # noqa: E402

if __name__ == "__main__":
    main()
