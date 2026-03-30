"""
Example: Use browser-use with Claude Code CLI (subscription-based, $0 API cost).

This uses your Claude Code subscription binary instead of the Anthropic API.
No API key needed - just have `claude` installed and logged in.

Usage:
    uv run python examples/models/claude_code.py
"""

import asyncio

from browser_use import Agent
from browser_use.llm.claude_code.chat import ChatClaudeCode

llm = ChatClaudeCode(
	model='sonnet',  # or 'opus', 'haiku'
	timeout=120.0,
)

agent = Agent(
	task='Go to google.com and search for "browser-use python library"',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
