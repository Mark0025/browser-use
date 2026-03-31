"""Network Interception Watchdog for Browser-Use sessions.

Captures API/XHR network activity via CDP Network domain and exposes
a rolling log of recent requests with URL, method, status, and selected
response headers. Designed for QA and debugging — the agent can see
which API calls the frontend makes and what comes back.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.network.events import (
	LoadingFailedEvent,
	RequestWillBeSentEvent,
	ResponseReceivedEvent,
)
from pydantic import ConfigDict, Field, PrivateAttr

from browser_use.browser.events import BrowserConnectedEvent, TabCreatedEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class NetworkEntry:
	"""A single captured network request/response pair."""

	__slots__ = (
		'request_id',
		'url',
		'method',
		'status',
		'status_text',
		'response_headers',
		'resource_type',
		'failed',
		'error_text',
		'timestamp',
	)

	def __init__(
		self,
		request_id: str,
		url: str,
		method: str,
		resource_type: str | None = None,
	) -> None:
		self.request_id = request_id
		self.url = url
		self.method = method
		self.status: int | None = None
		self.status_text: str | None = None
		self.response_headers: dict[str, str] = {}
		self.resource_type = resource_type
		self.failed = False
		self.error_text: str | None = None
		self.timestamp = time.time()

	def format_short(self) -> str:
		"""One-line summary for agent context injection."""
		status_str = str(self.status) if self.status is not None else 'PENDING'
		if self.failed:
			status_str = f'FAILED({self.error_text or "unknown"})'

		# Extract interesting headers
		header_parts: list[str] = []
		for key in ('x-data-source', 'x-cache', 'content-type'):
			val = self.response_headers.get(key)
			if val:
				header_parts.append(f'{key}: {val}')

		header_str = f' ({", ".join(header_parts)})' if header_parts else ''

		# Shorten URL to path only for readability
		path = self.url
		try:
			from urllib.parse import urlparse

			parsed = urlparse(self.url)
			path = parsed.path
			if parsed.query:
				path += f'?{parsed.query[:50]}'
		except Exception:
			pass

		return f'- {self.method} {path} → {status_str}{header_str}'


# Default URL patterns that indicate API/action calls worth capturing
DEFAULT_API_PATTERNS: list[str] = [
	'/api/',
	'/actions',
	'action=',
	'/graphql',
	'/trpc/',
	'/_next/data/',
]

# Resource types to always skip (static assets)
SKIP_RESOURCE_TYPES: set[str] = {
	'Stylesheet',
	'Image',
	'Media',
	'Font',
	'Manifest',
	'Preflight',
}


def _is_api_request(url: str, resource_type: str | None, api_patterns: list[str]) -> bool:
	"""Check if a request looks like an API call rather than a static asset fetch."""
	if resource_type and resource_type in SKIP_RESOURCE_TYPES:
		return False

	# XHR and Fetch are almost always API calls
	if resource_type in ('XHR', 'Fetch'):
		return True

	# Check URL patterns
	url_lower = url.lower()
	return any(pattern in url_lower for pattern in api_patterns)


class NetworkWatchdog(BaseWatchdog):
	"""Captures API network activity via CDP and exposes a rolling log.

	Attach to a BrowserSession to start capturing. Access the log via
	``get_network_log()`` or ``format_for_prompt()``.

	Unlike HarRecordingWatchdog, this watchdog:
	- Only captures API/XHR calls (not all HTTPS traffic)
	- Keeps a bounded in-memory log (no disk writes)
	- Provides real-time access to the log for agent context injection
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True,
		extra='forbid',
		validate_assignment=False,
		revalidate_instances='never',
	)

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [BrowserConnectedEvent, TabCreatedEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	max_entries: int = Field(default=100, description='Maximum number of entries to keep in the rolling log')
	api_patterns: list[str] = Field(
		default_factory=lambda: list(DEFAULT_API_PATTERNS),
		description='URL patterns that identify API calls worth capturing',
	)

	_entries: dict[str, NetworkEntry] = PrivateAttr(default_factory=dict)
	_log: deque[NetworkEntry] = PrivateAttr(default_factory=lambda: deque(maxlen=100))
	_enabled: bool = PrivateAttr(default=False)
	_enabled_sessions: set[str] = PrivateAttr(default_factory=set)

	def __init__(self, **kwargs: Any) -> None:
		super().__init__(**kwargs)
		self._log = deque(maxlen=self.max_entries)

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Enable Network domain on the root CDP session."""
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			session_id = cdp_session.session_id

			if session_id in self._enabled_sessions:
				return

			await cdp_session.cdp_client.send.Network.enable(session_id=session_id)

			cdp = self.browser_session.cdp_client.register
			cdp.Network.requestWillBeSent(self._on_request_will_be_sent)
			cdp.Network.responseReceived(self._on_response_received)
			cdp.Network.loadingFailed(self._on_loading_failed)

			self._enabled_sessions.add(session_id)
			self._enabled = True
			self.logger.info('🌐 Network interception enabled — capturing API calls')
		except Exception as e:
			self.logger.warning(f'Failed to enable network interception: {e}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Enable Network domain on new tab sessions."""
		if not self._enabled:
			return
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=event.target_id)
			session_id = cdp_session.session_id
			if session_id not in self._enabled_sessions:
				await cdp_session.cdp_client.send.Network.enable(session_id=session_id)
				self._enabled_sessions.add(session_id)
		except Exception as e:
			self.logger.debug(f'Network enable on new tab failed (non-fatal): {e}')

	# ============ CDP Event Handlers (sync) ============

	def _on_request_will_be_sent(self, params: RequestWillBeSentEvent, session_id: str | None) -> None:
		try:
			req = params.get('request', {}) if hasattr(params, 'get') else getattr(params, 'request', {})
			url = req.get('url') if isinstance(req, dict) else getattr(req, 'url', None)
			if not url:
				return

			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id:
				return

			resource_type = params.get('type') if hasattr(params, 'get') else getattr(params, 'type', None)
			method = (req.get('method') if isinstance(req, dict) else getattr(req, 'method', None)) or 'GET'

			if not _is_api_request(url, resource_type, self.api_patterns):
				return

			entry = NetworkEntry(
				request_id=request_id,
				url=url,
				method=method,
				resource_type=resource_type,
			)
			self._entries[request_id] = entry
			self._log.append(entry)
		except Exception:
			pass

	def _on_response_received(self, params: ResponseReceivedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id or request_id not in self._entries:
				return

			response = params.get('response', {}) if hasattr(params, 'get') else getattr(params, 'response', {})
			entry = self._entries[request_id]
			entry.status = response.get('status') if isinstance(response, dict) else getattr(response, 'status', None)
			entry.status_text = (
				response.get('statusText') if isinstance(response, dict) else getattr(response, 'statusText', None)
			)

			headers_raw = response.get('headers') if isinstance(response, dict) else getattr(response, 'headers', None)
			if headers_raw is None:
				entry.response_headers = {}
			elif isinstance(headers_raw, dict):
				entry.response_headers = {k.lower(): str(v) for k, v in headers_raw.items()}
			elif isinstance(headers_raw, list):
				entry.response_headers = {
					h.get('name', '').lower(): str(h.get('value') or '') for h in headers_raw if isinstance(h, dict)
				}
			else:
				try:
					headers_dict = dict(headers_raw) if hasattr(headers_raw, '__iter__') else {}
					entry.response_headers = {k.lower(): str(v) for k, v in headers_dict.items()}
				except Exception:
					entry.response_headers = {}

			# Log errors prominently
			if entry.status and entry.status >= 400:
				self.logger.debug(f'🌐 API error: {entry.method} {entry.url} → {entry.status}')
		except Exception:
			pass

	def _on_loading_failed(self, params: LoadingFailedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id or request_id not in self._entries:
				return
			entry = self._entries[request_id]
			entry.failed = True
			entry.error_text = params.get('errorText') if hasattr(params, 'get') else getattr(params, 'errorText', None)
			self.logger.debug(f'🌐 API failed: {entry.method} {entry.url} — {entry.error_text}')
		except Exception:
			pass

	# ============ Public API ============

	def get_entries(self, last_n: int | None = None) -> list[NetworkEntry]:
		"""Get captured network entries, optionally limited to the last N."""
		entries = list(self._log)
		if last_n is not None:
			entries = entries[-last_n:]
		return entries

	def get_error_entries(self) -> list[NetworkEntry]:
		"""Get only entries with 4xx/5xx status or failures."""
		return [e for e in self._log if e.failed or (e.status is not None and e.status >= 400)]

	def format_for_prompt(self, last_n: int = 15) -> str:
		"""Format recent network activity as a prompt section for agent context.

		Returns a markdown section showing recent API calls with status codes
		and key response headers. Highlights errors.
		"""
		entries = self.get_entries(last_n=last_n)
		if not entries:
			return ''

		lines = [f'## Network Activity (last {len(entries)} API calls)']
		for entry in entries:
			line = entry.format_short()
			# Highlight errors
			if entry.failed or (entry.status is not None and entry.status >= 400):
				line += ' ← ERROR'
			lines.append(line)

		# Summary of errors
		errors = self.get_error_entries()
		if errors:
			lines.append(f'\n⚠️ {len(errors)} API error(s) detected — investigate these!')

		return '\n'.join(lines)

	def clear(self) -> None:
		"""Clear all captured entries."""
		self._entries.clear()
		self._log.clear()
