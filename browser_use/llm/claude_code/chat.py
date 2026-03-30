"""
ChatClaudeCode - browser-use LLM provider that uses the Claude Code CLI binary.

This lets you run browser-use with your Claude Code subscription ($0 API cost)
by shelling out to `claude --print` instead of calling the Anthropic API directly.
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
	"""Convert browser-use messages into a single text prompt for claude --print."""
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
	A browser-use LLM provider that uses the Claude Code CLI binary.

	Uses your Claude Code subscription instead of API credits.
	Shells out to `claude --print --output-format json` for each invocation.
	"""

	model: str = 'sonnet'
	claude_binary: str = 'claude'
	timeout: float = 120.0
	extra_flags: list[str] = field(default_factory=list)

	@property
	def provider(self) -> str:
		return 'claude-code'

	@property
	def name(self) -> str:
		return f'claude-code:{self.model}'

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

		cmd = [
			self.claude_binary,
			'--print',
			'--output-format', 'json',
			'--model', self.model,
			'--no-session-persistence',
		]

		if output_format is not None:
			schema = output_format.model_json_schema()
			cmd.extend(['--json-schema', json.dumps(schema)])

		cmd.extend(self.extra_flags)

		try:
			proc = await asyncio.create_subprocess_exec(
				*cmd,
				stdin=asyncio.subprocess.PIPE,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
			)

			stdout, stderr = await asyncio.wait_for(
				proc.communicate(input=prompt.encode('utf-8')),
				timeout=self.timeout,
			)

			if proc.returncode != 0:
				error_msg = stderr.decode('utf-8', errors='replace').strip()
				raise ModelProviderError(
					message=f'claude CLI exited with code {proc.returncode}: {error_msg}',
					model=self.name,
				)

			raw_output = stdout.decode('utf-8').strip()

			if not raw_output:
				raise ModelProviderError(
					message='claude CLI returned empty output',
					model=self.name,
				)

			# Parse the JSON output from claude --print --output-format json
			try:
				cli_response = json.loads(raw_output)
			except json.JSONDecodeError:
				# If it's not JSON, treat as raw text (shouldn't happen with --output-format json)
				cli_response = {'result': raw_output}

			# Extract result from claude CLI JSON output
			result_text = ''
			structured_data = None
			if isinstance(cli_response, dict):
				# Check for structured_output first (used with --json-schema)
				structured_data = cli_response.get('structured_output')
				result_text = cli_response.get('result', '')
			elif isinstance(cli_response, list):
				for block in cli_response:
					if isinstance(block, dict):
						if block.get('type') == 'result':
							structured_data = block.get('structured_output')
							result_text = block.get('result', '')
							break
						elif block.get('type') == 'text':
							result_text += block.get('text', '')
			if not result_text and not structured_data and isinstance(cli_response, str):
				result_text = cli_response

			# Extract usage from CLI response if available
			cli_usage = cli_response.get('usage', {}) if isinstance(cli_response, dict) else {}
			input_tokens = cli_usage.get('input_tokens', 0)
			output_tokens = cli_usage.get('output_tokens', 0)
			cached_tokens = cli_usage.get('cache_read_input_tokens', 0)
			cache_creation = cli_usage.get('cache_creation_input_tokens', 0)

			usage = ChatInvokeUsage(
				prompt_tokens=input_tokens + cached_tokens,
				completion_tokens=output_tokens,
				total_tokens=input_tokens + output_tokens + cached_tokens,
				prompt_cached_tokens=cached_tokens if cached_tokens else None,
				prompt_cache_creation_tokens=cache_creation if cache_creation else None,
				prompt_image_tokens=None,
			)

			if output_format is not None:
				# For structured output, use structured_data if available, fall back to result_text
				try:
					if structured_data is not None:
						completion = output_format.model_validate(structured_data)
					elif result_text:
						try:
							completion = output_format.model_validate_json(result_text)
						except Exception:
							data = json.loads(result_text)
							completion = output_format.model_validate(data)
					else:
						raise ValueError('No structured_output or result in CLI response')
				except Exception as e:
					raise ModelProviderError(
						message=f'Failed to parse structured output: {e}\nRaw: {str(structured_data or result_text)[:500]}',
						model=self.name,
					) from e

				return ChatInvokeCompletion(
					completion=completion,
					usage=usage,
					stop_reason=cli_response.get('stop_reason', 'end_turn') if isinstance(cli_response, dict) else 'end_turn',
				)
			else:
				return ChatInvokeCompletion(
					completion=result_text,
					usage=usage,
					stop_reason=cli_response.get('stop_reason', 'end_turn') if isinstance(cli_response, dict) else 'end_turn',
				)

		except asyncio.TimeoutError as e:
			raise ModelProviderError(
				message=f'claude CLI timed out after {self.timeout}s',
				model=self.name,
			) from e
		except ModelProviderError:
			raise
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
