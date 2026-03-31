"""
Tests for NetworkWatchdog — verifies that API network interception captures
requests/responses and formats them correctly for agent context injection.

Uses pytest-httpserver to create a local test server with API endpoints.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.network_watchdog import (
	NetworkEntry,
	NetworkWatchdog,
	_is_api_request,
)


class TestNetworkEntryFormat:
	"""Test NetworkEntry formatting without browser."""

	def test_format_short_basic(self):
		entry = NetworkEntry(
			request_id='r1',
			url='https://example.com/api/health',
			method='GET',
			resource_type='Fetch',
		)
		entry.status = 200
		result = entry.format_short()
		assert '- GET /api/health' in result
		assert '200' in result

	def test_format_short_with_headers(self):
		entry = NetworkEntry(
			request_id='r2',
			url='https://example.com/api/blogs',
			method='POST',
			resource_type='XHR',
		)
		entry.status = 200
		entry.response_headers = {
			'x-data-source': 'db:blogs',
			'x-cache': 'miss',
			'content-type': 'application/json',
		}
		result = entry.format_short()
		assert 'POST /api/blogs' in result
		assert '200' in result
		assert 'x-data-source: db:blogs' in result
		assert 'x-cache: miss' in result

	def test_format_short_error(self):
		entry = NetworkEntry(
			request_id='r3',
			url='https://example.com/api/missing',
			method='GET',
			resource_type='Fetch',
		)
		entry.status = 404
		result = entry.format_short()
		assert '404' in result

	def test_format_short_failed(self):
		entry = NetworkEntry(
			request_id='r4',
			url='https://example.com/api/timeout',
			method='GET',
			resource_type='Fetch',
		)
		entry.failed = True
		entry.error_text = 'net::ERR_CONNECTION_TIMED_OUT'
		result = entry.format_short()
		assert 'FAILED' in result
		assert 'net::ERR_CONNECTION_TIMED_OUT' in result

	def test_format_short_with_query(self):
		entry = NetworkEntry(
			request_id='r5',
			url='https://example.com/api/search?q=test&page=1',
			method='GET',
			resource_type='Fetch',
		)
		entry.status = 200
		result = entry.format_short()
		assert '/api/search?' in result


class TestIsApiRequest:
	"""Test the _is_api_request filter function."""

	def test_xhr_is_api(self):
		assert _is_api_request('https://example.com/anything', 'XHR', ['/api/'])

	def test_fetch_is_api(self):
		assert _is_api_request('https://example.com/anything', 'Fetch', ['/api/'])

	def test_api_url_pattern(self):
		assert _is_api_request('https://example.com/api/users', 'Document', ['/api/'])

	def test_actions_url_pattern(self):
		assert _is_api_request('https://example.com/actions.ts', None, ['/actions'])

	def test_stylesheet_skipped(self):
		assert not _is_api_request('https://example.com/api/styles.css', 'Stylesheet', ['/api/'])

	def test_image_skipped(self):
		assert not _is_api_request('https://example.com/api/logo.png', 'Image', ['/api/'])

	def test_font_skipped(self):
		assert not _is_api_request('https://example.com/fonts/arial.woff2', 'Font', ['/api/'])

	def test_no_match(self):
		assert not _is_api_request('https://example.com/page.html', 'Document', ['/api/'])


class TestNetworkWatchdogFormatting:
	"""Test NetworkWatchdog formatting without browser."""

	@pytest.fixture
	def watchdog_with_entries(self):
		"""Create a mock watchdog scenario by directly populating entries."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		NetworkWatchdog.model_rebuild()
		watchdog = NetworkWatchdog(
			event_bus=session.event_bus,
			browser_session=session,
			max_entries=50,
		)

		# Manually add entries to test formatting
		entries_data = [
			('r1', 'https://dev.example.com/api/health', 'GET', 200, {}),
			('r2', 'https://dev.example.com/api/blogs', 'POST', 200, {'x-data-source': 'db:blogs'}),
			('r3', 'https://dev.example.com/api/preview-image/abc', 'GET', 404, {}),
			('r4', 'https://dev.example.com/api/settings', 'PUT', 500, {}),
		]

		for rid, url, method, status, headers in entries_data:
			entry = NetworkEntry(request_id=rid, url=url, method=method, resource_type='Fetch')
			entry.status = status
			entry.response_headers = headers
			watchdog._entries[rid] = entry
			watchdog._log.append(entry)

		return watchdog

	def test_format_for_prompt(self, watchdog_with_entries):
		result = watchdog_with_entries.format_for_prompt(last_n=10)
		assert '## Network Activity' in result
		assert 'GET /api/health' in result
		assert 'POST /api/blogs' in result
		assert '404' in result
		assert '500' in result
		assert 'ERROR' in result
		assert 'x-data-source: db:blogs' in result

	def test_format_for_prompt_empty(self):
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		NetworkWatchdog.model_rebuild()
		watchdog = NetworkWatchdog(
			event_bus=session.event_bus,
			browser_session=session,
		)
		result = watchdog.format_for_prompt()
		assert result == ''

	def test_get_error_entries(self, watchdog_with_entries):
		errors = watchdog_with_entries.get_error_entries()
		assert len(errors) == 2  # 404 and 500
		statuses = {e.status for e in errors}
		assert 404 in statuses
		assert 500 in statuses

	def test_get_entries_last_n(self, watchdog_with_entries):
		entries = watchdog_with_entries.get_entries(last_n=2)
		assert len(entries) == 2
		# Should be the last two entries
		assert entries[0].url == 'https://dev.example.com/api/preview-image/abc'
		assert entries[1].url == 'https://dev.example.com/api/settings'

	def test_clear(self, watchdog_with_entries):
		assert len(watchdog_with_entries._log) > 0
		watchdog_with_entries.clear()
		assert len(watchdog_with_entries._log) == 0
		assert len(watchdog_with_entries._entries) == 0

	def test_error_summary_in_prompt(self, watchdog_with_entries):
		result = watchdog_with_entries.format_for_prompt()
		assert '2 API error(s) detected' in result


class TestNetworkWatchdogLive:
	"""Integration tests — verify watchdog captures real browser network traffic."""

	@pytest.fixture
	async def session_with_watchdog(self):
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		NetworkWatchdog.model_rebuild()
		watchdog = NetworkWatchdog(
			event_bus=session.event_bus,
			browser_session=session,
			max_entries=50,
		)
		watchdog.attach_to_session()
		await session.start()
		yield session, watchdog
		await session.kill()

	async def _wait_for_entries(self, watchdog: NetworkWatchdog, url_fragment: str, timeout: float = 5.0) -> list[NetworkEntry]:
		"""Poll for entries matching a URL fragment, with timeout."""
		deadline = asyncio.get_event_loop().time() + timeout
		while asyncio.get_event_loop().time() < deadline:
			entries = [e for e in watchdog.get_entries() if url_fragment in e.url]
			if entries:
				return entries
			await asyncio.sleep(0.2)
		return []

	async def test_captures_api_call(self, httpserver: HTTPServer, session_with_watchdog):
		session, watchdog = session_with_watchdog

		# Set up test API endpoint
		httpserver.expect_request('/api/test-endpoint').respond_with_json(
			{'status': 'ok', 'data': [1, 2, 3]},
			status=200,
			headers={'X-Data-Source': 'db:test'},
		)

		# Create a page that makes a fetch call to our test API
		page_html = f"""
		<html><body>
		<h1>Network Test</h1>
		<script>
			fetch('{httpserver.url_for('/api/test-endpoint')}')
				.then(r => r.json())
				.then(d => document.title = 'DONE');
		</script>
		</body></html>
		"""
		httpserver.expect_request('/test-page').respond_with_data(page_html, content_type='text/html')

		from browser_use.browser.events import NavigateToUrlEvent

		await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/test-page')))

		# Wait for the API call to be captured
		api_entries = await self._wait_for_entries(watchdog, '/api/test-endpoint', timeout=8.0)
		assert len(api_entries) >= 1, f'Expected to capture /api/test-endpoint, got: {[e.url for e in watchdog.get_entries()]}'
		assert api_entries[0].method == 'GET'
		# Status may or may not be populated depending on CDP event timing
		# The key assertion is that the request was captured

	async def test_captures_error_response(self, httpserver: HTTPServer, session_with_watchdog):
		session, watchdog = session_with_watchdog

		# Set up a failing API endpoint
		httpserver.expect_request('/api/broken').respond_with_json({'error': 'not found'}, status=404)

		page_html = f"""
		<html><body>
		<h1>Error Test</h1>
		<script>
			fetch('{httpserver.url_for('/api/broken')}')
				.then(r => document.title = 'DONE');
		</script>
		</body></html>
		"""
		httpserver.expect_request('/error-page').respond_with_data(page_html, content_type='text/html')

		from browser_use.browser.events import NavigateToUrlEvent

		await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/error-page')))

		# Wait for the API call to be captured
		api_entries = await self._wait_for_entries(watchdog, '/api/broken', timeout=8.0)
		assert len(api_entries) >= 1, f'Expected to capture /api/broken, got: {[e.url for e in watchdog.get_entries()]}'

	async def test_format_for_prompt_after_capture(self, httpserver: HTTPServer, session_with_watchdog):
		session, watchdog = session_with_watchdog

		httpserver.expect_request('/api/data').respond_with_json({'items': []}, status=200)

		page_html = f"""
		<html><body>
		<script>
			fetch('{httpserver.url_for('/api/data')}')
				.then(r => document.title = 'DONE');
		</script>
		</body></html>
		"""
		httpserver.expect_request('/format-test').respond_with_data(page_html, content_type='text/html')

		from browser_use.browser.events import NavigateToUrlEvent

		await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/format-test')))

		# Wait for capture
		await self._wait_for_entries(watchdog, '/api/data', timeout=8.0)

		prompt = watchdog.format_for_prompt()
		assert '## Network Activity' in prompt
		assert '/api/data' in prompt
