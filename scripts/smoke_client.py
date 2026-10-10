"""End-to-end check: launch run_server.py over stdio exactly as Claude Code
does, list the tools, and have it say a sentence through the real speakers.

    python scripts/smoke_client.py ["text to say"]

Prints the tool list, the server's reply, and how long the utterance took.
A sentence that returns in well under a second was not actually synthesised.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main(text: str) -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", os.path.join(ROOT, "run_server.py")],
        env={**os.environ, "PYTHONUTF8": "1"},
        cwd=ROOT,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", ", ".join(t.name for t in tools.tools))
            voices = await session.call_tool("list_voices", {})
            print("voices:", [c.text for c in voices.content])
            t0 = time.perf_counter()
            res = await session.call_tool("speak", {"text": text})
            print("speak ->", res.content[0].text, "(isError=%s)" % res.isError)
            # the tool returns as soon as the message is queued; wait for the
            # utterance by asking for another one with interrupt=False and
            # polling stop_speaking's purge count is overkill - just sleep by
            # length: ~15 chars/sec is a slow upper bound for these voices.
            await asyncio.sleep(min(30, 1 + len(text) / 12))
            print("elapsed %.1fs" % (time.perf_counter() - t0))
            return 1 if res.isError else 0


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "クロードトークが起動しました。ゆっくりしていってね。"
    raise SystemExit(asyncio.run(main(msg)))
