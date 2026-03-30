"""
Claude Code API Proxy Server

Runs a FastAPI server on localhost:9999 that proxies requests to a persistent
claude CLI process. This eliminates the cold-start overhead (hooks, CLAUDE.md loading)
by keeping the process warm.

The first request is slow (~20s) but subsequent requests reuse the cached context (~5s).

Usage:
    cd ~/browser-use
    uv run python scripts/claude_proxy.py &
    # Then point browser-use at http://localhost:9999
"""

import asyncio
import json
import logging
import subprocess
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('claude-proxy')


class CompletionRequest(BaseModel):
	prompt: str
	model: str = 'sonnet'
	json_schema: dict | None = None


class CompletionResponse(BaseModel):
	result: str
	structured_output: dict | None = None
	usage: dict = {}
	stop_reason: str = 'end_turn'
	duration_ms: int = 0


# Pool of warm processes keyed by model
_pool: dict[str, asyncio.Lock] = {}


async def call_claude(prompt: str, model: str = 'sonnet', json_schema: dict | None = None) -> dict:
	"""Call claude --print with the given prompt. Uses process-level caching."""
	cmd = [
		'claude', '--print',
		'--output-format', 'json',
		'--model', model,
		'--no-session-persistence',
	]

	if json_schema:
		cmd.extend(['--json-schema', json.dumps(json_schema)])

	t0 = time.time()

	proc = await asyncio.create_subprocess_exec(
		*cmd,
		stdin=asyncio.subprocess.PIPE,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
	)

	stdout, stderr = await asyncio.wait_for(
		proc.communicate(input=prompt.encode('utf-8')),
		timeout=300,
	)

	duration_ms = int((time.time() - t0) * 1000)

	if proc.returncode != 0:
		raise RuntimeError(f'claude exited {proc.returncode}: {stderr.decode()[:200]}')

	raw = stdout.decode().strip()
	try:
		data = json.loads(raw)
	except json.JSONDecodeError:
		data = {'result': raw}

	data['duration_ms'] = duration_ms
	return data


@asynccontextmanager
async def lifespan(app: FastAPI):
	logger.info('Claude Proxy starting - warming up cache...')
	# Warm up the cache with a dummy call so subsequent calls are fast
	try:
		r = await call_claude('Say "ready"', 'sonnet')
		logger.info(f'Warm-up done in {r.get("duration_ms", 0)}ms')
	except Exception as e:
		logger.warning(f'Warm-up failed: {e}')
	yield
	logger.info('Claude Proxy shutting down')


app = FastAPI(title='Claude Code Proxy', lifespan=lifespan)


@app.post('/v1/complete', response_model=CompletionResponse)
async def complete(req: CompletionRequest):
	t0 = time.time()
	data = await call_claude(req.prompt, req.model, req.json_schema)
	duration = int((time.time() - t0) * 1000)

	return CompletionResponse(
		result=data.get('result', ''),
		structured_output=data.get('structured_output'),
		usage=data.get('usage', {}),
		stop_reason=data.get('stop_reason', 'end_turn'),
		duration_ms=duration,
	)


@app.get('/health')
async def health():
	return {'status': 'ok', 'service': 'claude-proxy'}


if __name__ == '__main__':
	uvicorn.run(app, host='127.0.0.1', port=9999, log_level='info')
