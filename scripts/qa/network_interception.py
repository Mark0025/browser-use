"""
Network interception utilities for QA scripts.

Provides helpers to attach network monitoring to a BrowserSession
and inject captured API activity into the agent's context.

Usage:
    from network_interception import attach_network_watchdog, network_prompt_section

    session, tmp_dir = create_browser_session()
    watchdog = attach_network_watchdog(session)

    # Later, get a prompt section for agent context:
    network_section = network_prompt_section(watchdog, last_n=15)
"""

from __future__ import annotations

from browser_use import BrowserSession
from browser_use.browser.watchdogs.network_watchdog import NetworkWatchdog


def attach_network_watchdog(
	session: BrowserSession,
	max_entries: int = 100,
	api_patterns: list[str] | None = None,
) -> NetworkWatchdog:
	"""Attach a NetworkWatchdog to a BrowserSession.

	Call this BEFORE the session connects to the browser. The watchdog
	will automatically start capturing API calls once the browser connects.

	Args:
		session: The BrowserSession to monitor.
		max_entries: Maximum number of entries to keep in the rolling log.
		api_patterns: Custom URL patterns to identify API calls.
			Defaults to common patterns like '/api/', '/actions', etc.

	Returns:
		The attached NetworkWatchdog instance. Use its ``format_for_prompt()``
		method to get a formatted string for agent context injection.
	"""
	NetworkWatchdog.model_rebuild()

	kwargs: dict = {
		'event_bus': session.event_bus,
		'browser_session': session,
		'max_entries': max_entries,
	}
	if api_patterns is not None:
		kwargs['api_patterns'] = api_patterns

	watchdog = NetworkWatchdog(**kwargs)
	watchdog.attach_to_session()
	return watchdog


def network_prompt_section(watchdog: NetworkWatchdog, last_n: int = 15) -> str:
	"""Get a formatted prompt section from the watchdog's captured entries.

	Returns an empty string if no API calls have been captured yet.
	"""
	return watchdog.format_for_prompt(last_n=last_n)
