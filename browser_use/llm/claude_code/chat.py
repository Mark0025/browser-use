"""
ChatClaudeCode - browser-use LLM provider using the Claude Code Python SDK.

Uses your Claude Code subscription ($0 API cost) via the claude-code-sdk package,
which manages the CLI subprocess internally with proper streaming.
"""

import asyncio
import json
import logging
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

	Uses your subscription — no API key needed.
	"""

	model: str = 'sonnet'
	timeout: float = 300.0
	system_prompt: str = 'You are a browser automation assistant. Follow instructions precisely. Be concise. When asked for structured output, return ONLY valid JSON.'
	max_turns: int = 1
	extra_flags: list[str] = field(default_factory=list)

	@property
	def provider(self) -> str:
		return 'claude-code'

	@property
	def name(self) -> str:
		return f'claude-code:{self.model}'

	async def _call_sdk(self, prompt: str) -> str:
		"""Call Claude via the Python SDK, handling unknown message types gracefully."""
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
				# Collect text content from assistant messages
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
				# We already got content before the error, use it
				logger.warning(f'SDK parse error after receiving content: {err_str[:100]}')
			elif 'rate_limit' in err_str.lower():
				logger.warning('Rate limited, retrying in 5s...')
				await asyncio.sleep(5)
				return await self._call_sdk(prompt)
			else:
				raise ModelProviderError(message=f'Claude SDK error: {err_str[:300]}', model=self.name) from e

		return '\n'.join(texts)

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
