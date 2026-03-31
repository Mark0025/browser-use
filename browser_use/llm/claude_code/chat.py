"""
ChatClaudeCode - browser-use LLM provider using the Claude Code Python SDK.

Uses your Claude Code subscription ($0 API cost) via the claude-code-sdk package.

Performance optimization: uses ClaudeSDKClient to maintain a persistent subprocess
connection, eliminating the ~10s cold-start overhead on every call after the first.
The first call pays the startup cost; subsequent calls go straight to the API (~3-5s).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
	"""Convert browser-use messages into a single text prompt."""
	parts: list[str] = []
	for msg in messages:
		if isinstance(msg, SystemMessage):
			parts.append(f'[SYSTEM]\n{msg.text}')
		elif isinstance(msg, UserMessage):
			parts.append(f'[USER]\n{msg.text}')
		elif isinstance(msg, AssistantMessage):
			parts.append(f'[ASSISTANT]\n{msg.text}')
	return '\n\n'.join(parts)


@dataclass
class ChatClaudeCode(BaseChatModel):
	"""
	browser-use LLM provider using the Claude Code Python SDK.

	Uses ClaudeSDKClient for persistent session reuse — the CLI subprocess
	stays alive between calls, cutting per-call overhead from ~23s to ~3-5s
	after the initial connection.
	"""

	model: str = 'sonnet'
	timeout: float = 300.0
	system_prompt: str = 'You are a browser automation assistant. Follow instructions precisely. Be concise. When asked for structured output, return ONLY valid JSON.'
	max_turns: int = 1
	extra_flags: list[str] = field(default_factory=list)
	_client: Any = field(default=None, init=False, repr=False)
	_client_lock: Any = field(default=None, init=False, repr=False)
	_call_count: int = field(default=0, init=False, repr=False)

	def __post_init__(self) -> None:
		self._client_lock = asyncio.Lock()

	@property
	def provider(self) -> str:
		return 'claude-code'

	@property
	def name(self) -> str:
		return f'claude-code:{self.model}'

	async def _ensure_client(self) -> Any:
		"""Get or create the persistent ClaudeSDKClient connection."""
		from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

		if self._client_lock is None:
			self._client_lock = asyncio.Lock()

		async with self._client_lock:
			if self._client is not None:
				return self._client

			logger.info('ChatClaudeCode: establishing persistent SDK connection (first call pays cold-start cost)...')
			start = time.monotonic()

			opts = ClaudeCodeOptions(
				model=self.model,
				max_turns=self.max_turns,
				system_prompt=self.system_prompt,
			)
			client = ClaudeSDKClient(options=opts)
			await client.connect()
			self._client = client

			elapsed = time.monotonic() - start
			logger.info(f'ChatClaudeCode: persistent connection established in {elapsed:.1f}s')
			return self._client

	async def _call_sdk(self, prompt: str) -> str:
		"""Call Claude via the persistent SDK client, falling back to query() on failure."""
		self._call_count += 1
		call_num = self._call_count
		start = time.monotonic()

		try:
			return await self._call_sdk_persistent(prompt, call_num, start)
		except Exception as e:
			err_str = str(e)
			logger.warning(f'ChatClaudeCode: persistent client failed (call #{call_num}): {err_str[:200]}')
			# Reset client so next call reconnects
			await self._disconnect_client()
			# Fall back to one-shot query() for this call
			return await self._call_sdk_oneshot(prompt, call_num, start)

	async def _call_sdk_persistent(self, prompt: str, call_num: int, start: float) -> str:
		"""Send a query through the persistent ClaudeSDKClient."""
		from claude_code_sdk import ResultMessage as SdkResultMessage

		client = await self._ensure_client()
		await client.query(prompt)

		texts: list[str] = []
		async for msg in client.receive_response():
			if hasattr(msg, 'content') and msg.content:
				content = msg.content
				if isinstance(content, str):
					texts.append(content)
				elif isinstance(content, list):
					for block in content:
						if hasattr(block, 'text'):
							texts.append(block.text)
						elif isinstance(block, dict) and 'text' in block:
							texts.append(block['text'])
			if isinstance(msg, SdkResultMessage):
				break

		elapsed = time.monotonic() - start
		logger.info(f'ChatClaudeCode: call #{call_num} completed in {elapsed:.1f}s (persistent)')

		if not texts:
			raise ModelProviderError(message='Empty response from persistent SDK client', model=self.name)

		return '\n'.join(texts)

	async def _call_sdk_oneshot(self, prompt: str, call_num: int, start: float) -> str:
		"""Fallback: use one-shot query() — spawns a new process (slower, but reliable)."""
		from claude_code_sdk import ClaudeCodeOptions, query

		texts: list[str] = []

		try:
			async for msg in query(
				prompt=prompt,
				options=ClaudeCodeOptions(
					model=self.model,
					max_turns=self.max_turns,
					system_prompt=self.system_prompt,
				),
			):
				if hasattr(msg, 'content') and msg.content:
					content = msg.content
					if isinstance(content, str):
						texts.append(content)
					elif isinstance(content, list):
						for block in content:
							if hasattr(block, 'text'):
								texts.append(block.text)
							elif isinstance(block, dict) and 'text' in block:
								texts.append(block['text'])
		except Exception as e:
			err_str = str(e)
			# Handle rate_limit_event parse errors from SDK
			if 'Unknown message type' in err_str and texts:
				logger.warning(f'SDK parse error after receiving content: {err_str[:100]}')
			elif 'rate_limit' in err_str.lower():
				logger.warning('Rate limited, retrying in 5s...')
				await asyncio.sleep(5)
				return await self._call_sdk_oneshot(prompt, call_num, time.monotonic())
			else:
				raise ModelProviderError(message=f'Claude SDK error: {err_str[:300]}', model=self.name) from e

		elapsed = time.monotonic() - start
		logger.info(f'ChatClaudeCode: call #{call_num} completed in {elapsed:.1f}s (oneshot fallback)')

		return '\n'.join(texts)

	async def _disconnect_client(self) -> None:
		"""Disconnect the persistent client if active."""
		if self._client is not None:
			try:
				await self._client.disconnect()
			except Exception:
				pass
			self._client = None

	async def close(self) -> None:
		"""Clean up the persistent SDK connection. Call when done with the provider."""
		await self._disconnect_client()

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		prompt = _messages_to_prompt(messages)

		if output_format is not None:
			schema = output_format.model_json_schema()
			prompt += f'\n\n[RESPOND WITH ONLY VALID JSON matching this schema. No markdown fences, no explanation, JUST the JSON object.]\n{json.dumps(schema, indent=2)}'

		try:
			result_text = await asyncio.wait_for(
				self._call_sdk(prompt),
				timeout=self.timeout,
			)
		except asyncio.TimeoutError as e:
			raise ModelProviderError(message=f'Claude SDK timed out after {self.timeout}s', model=self.name) from e
		except ModelProviderError:
			raise
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		usage = ChatInvokeUsage(
			prompt_tokens=0,
			completion_tokens=0,
			total_tokens=0,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
		)

		if output_format is not None:
			try:
				text = result_text.strip()
				# Strip markdown code fences if present
				if text.startswith('```'):
					text = text.split('\n', 1)[1] if '\n' in text else text[3:]
					if text.endswith('```'):
						text = text[:-3]
					text = text.strip()
				try:
					completion = output_format.model_validate_json(text)
				except Exception:
					data = json.loads(text)
					completion = output_format.model_validate(data)
			except Exception as e:
				raise ModelProviderError(
					message=f'Failed to parse structured output: {e}\nRaw: {result_text[:500]}',
					model=self.name,
				) from e

			return ChatInvokeCompletion(completion=completion, usage=usage, stop_reason='end_turn')
		else:
			return ChatInvokeCompletion(completion=result_text, usage=usage, stop_reason='end_turn')
