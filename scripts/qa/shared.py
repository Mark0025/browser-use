"""
Shared utilities for browser-use QA scripts.

- Sitemap fetching from /api/dev/sitemap
- Chrome profile copying (no need to close Chrome)
- Human takeover detection + logging
- Report saving
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger

from browser_use import BrowserProfile, BrowserSession
from browser_use.llm.claude_code.chat import ChatClaudeCode

# Base URL for the dev site
DEV_URL = 'https://dev.fairdealhousebuyer.com'

# Reports directory
REPORTS_DIR = Path(__file__).parent.parent / 'qa_reports'
REPORTS_DIR.mkdir(exist_ok=True)

# Test results persistence file
TEST_RESULTS_FILE = REPORTS_DIR / 'test_results.json'


class TestResultMemory:
	"""Persistent test result tracking across QA runs.

	Maintains a test_results.json that records which sections have been tested,
	when, how many steps were used, and any issues found. On subsequent runs,
	the agent prompt includes previous results so it can skip passing sections
	and prioritize untested or failed areas.
	"""

	def __init__(self, results_path: Path = TEST_RESULTS_FILE):
		self.results_path = results_path
		self.data: dict = self._load()

	def _load(self) -> dict:
		"""Load existing results or initialize empty state."""
		if self.results_path.exists():
			try:
				data = json.loads(self.results_path.read_text())
				logger.info(f'Loaded test results: {len(data.get("sections", {}))} sections tracked')
				return data
			except (json.JSONDecodeError, KeyError) as e:
				logger.warning(f'Corrupt test_results.json, starting fresh: {e}')
		return {'last_run': None, 'sections': {}}

	def save(self) -> None:
		"""Persist current results to disk."""
		self.data['last_run'] = datetime.now(timezone.utc).isoformat()
		self.results_path.write_text(json.dumps(self.data, indent=2, default=str))
		logger.success(f'Saved test results to {self.results_path}')

	def get_section(self, section_id: str) -> dict:
		"""Get a section's test result, or a default 'not_tested' entry."""
		return self.data.setdefault('sections', {}).get(
			section_id,
			{
				'status': 'not_tested',
				'tested_at': None,
				'steps_used': 0,
				'issues_found': [],
			},
		)

	def mark_tested(
		self,
		section_id: str,
		status: str = 'pass',
		steps_used: int = 0,
		issues_found: list[str] | None = None,
	) -> None:
		"""Record a section as tested with its result."""
		assert status in ('pass', 'fail', 'partial', 'not_tested'), f'Invalid status: {status}'
		self.data.setdefault('sections', {})[section_id] = {
			'status': status,
			'tested_at': datetime.now(timezone.utc).isoformat(),
			'steps_used': steps_used,
			'issues_found': issues_found or [],
		}

	def invalidate(self, section_id: str) -> None:
		"""Mark a section as needing re-test (e.g., code changed)."""
		sections = self.data.get('sections', {})
		if section_id in sections:
			sections[section_id]['status'] = 'not_tested'
			sections[section_id]['tested_at'] = None
			logger.info(f'Invalidated section: {section_id}')

	def invalidate_all(self) -> None:
		"""Reset all sections to not_tested."""
		for section_id in self.data.get('sections', {}):
			self.invalidate(section_id)
		logger.info('Invalidated all sections')

	def sections_by_status(self, status: str) -> list[str]:
		"""Get all section IDs with a given status."""
		return [sid for sid, info in self.data.get('sections', {}).items() if info.get('status') == status]

	def untested_sections(self) -> list[str]:
		"""Get sections that have never been tested or were invalidated."""
		return self.sections_by_status('not_tested')

	def passed_sections(self) -> list[str]:
		"""Get sections that passed."""
		return self.sections_by_status('pass')

	def failed_sections(self) -> list[str]:
		"""Get sections that failed or had issues."""
		return self.sections_by_status('fail') + self.sections_by_status('partial')

	def ensure_sections_tracked(self, section_ids: list[str]) -> None:
		"""Register sections that should be tracked, without overwriting existing results."""
		sections = self.data.setdefault('sections', {})
		for sid in section_ids:
			if sid not in sections:
				sections[sid] = {
					'status': 'not_tested',
					'tested_at': None,
					'steps_used': 0,
					'issues_found': [],
				}

	def prompt_section(self) -> str:
		"""Generate a prompt section summarizing previous test results.

		This is injected into the agent task so it knows what to skip and what to prioritize.
		"""
		sections = self.data.get('sections', {})
		if not sections:
			return '## Previous Test Results\nNo previous test results — test everything.'

		lines = ['## Previous Test Results (skip PASSED sections unless code changed):']

		# Group by status for clear prioritization
		for sid, info in sorted(sections.items(), key=lambda x: _status_sort_key(x[1].get('status', 'not_tested'))):
			status = info.get('status', 'not_tested')
			tested_at = info.get('tested_at')
			steps = info.get('steps_used', 0)
			issues = info.get('issues_found', [])

			if status == 'pass':
				icon = '✅'
				detail = f'PASSED {tested_at or "unknown"} ({steps} steps)'
				if issues:
					detail += f' — found issues: {", ".join(issues)}'
			elif status == 'fail':
				icon = '❌'
				detail = f'FAILED {tested_at or "unknown"}'
				if issues:
					detail += f' — issues: {", ".join(issues)}'
				detail += ' — RE-TEST THIS'
			elif status == 'partial':
				icon = '⚠️'
				detail = f'PARTIAL {tested_at or "unknown"}'
				if issues:
					detail += f' — issues: {", ".join(issues)}'
				detail += ' — NEEDS MORE TESTING'
			else:
				icon = '🔲'
				detail = 'NOT TESTED — test this'

			lines.append(f'- {icon} **{sid}**: {detail}')

		# Add priority guidance
		untested = self.untested_sections()
		failed = self.failed_sections()
		if untested:
			lines.append(f'\n**PRIORITY: Test these first:** {", ".join(untested)}')
		if failed:
			lines.append(f'**RE-TEST these (previously failed):** {", ".join(failed)}')

		passed = self.passed_sections()
		if passed:
			lines.append(f'**SKIP these (already passed):** {", ".join(passed)}')

		return '\n'.join(lines)

	def update_from_report(self, report_text: str, all_section_ids: list[str]) -> None:
		"""Parse a QA report and update section results based on keywords.

		Scans the report for section names and PASS/FAIL/BROKEN keywords to auto-update
		results. This is a best-effort heuristic — manual mark_tested() calls are more precise.
		"""
		report_upper = report_text.upper()

		for sid in all_section_ids:
			# Normalize section id to searchable form
			search_term = sid.replace('_', ' ').upper()

			if search_term not in report_upper:
				continue

			# Find the context: from the section mention to the next section header or 150 chars
			idx = report_upper.index(search_term)
			end = len(report_upper)
			# Look for next "### " section header after this one
			next_section = report_upper.find('\n###', idx + len(search_term))
			if next_section != -1:
				end = next_section
			context = report_upper[idx : min(end, idx + 150)]

			if 'PASS' in context and 'FAIL' not in context:
				self.mark_tested(sid, status='pass')
			elif 'FAIL' in context or 'BROKEN' in context or 'ERROR' in context:
				# Extract issues if possible
				issues = []
				if 'ISSUE' in context or 'BUG' in context:
					issues.append('see report for details')
				self.mark_tested(sid, status='fail', issues_found=issues)
			elif 'PARTIAL' in context or 'INCONCLUSIVE' in context:
				self.mark_tested(sid, status='partial')


def _status_sort_key(status: str) -> int:
	"""Sort sections: not_tested first, then fail, partial, pass last."""
	return {'not_tested': 0, 'fail': 1, 'partial': 2, 'pass': 3}.get(status, 0)


async def fetch_sitemap() -> dict | None:
	"""Fetch the dev sitemap from /api/dev/sitemap. Returns None if not available."""
	try:
		async with httpx.AsyncClient(verify=False, timeout=10) as client:
			resp = await client.get(f'{DEV_URL}/api/dev/sitemap')
			if resp.status_code == 200:
				data = resp.json()
				logger.success(
					f'Fetched sitemap: {len(data.get("public", []))} public, {len(data.get("admin", {}).get("tabs", []))} admin tabs'
				)
				return data
			else:
				logger.warning(f'Sitemap returned {resp.status_code} — using hardcoded fallback')
	except Exception as e:
		logger.warning(f'Sitemap fetch failed ({e}) — using hardcoded fallback')
	return None


def get_sitemap_or_fallback() -> dict:
	"""Get sitemap synchronously, with hardcoded fallback."""
	sitemap = asyncio.get_event_loop().run_until_complete(fetch_sitemap()) if asyncio.get_event_loop().is_running() else None

	if sitemap:
		return sitemap

	# Hardcoded fallback from our QA runs
	return {
		'public': [
			{'path': '/', 'name': 'Homepage'},
			{'path': '/reviews', 'name': 'Reviews'},
			{'path': '/about', 'name': 'About'},
			{'path': '/how-it-works', 'name': 'How It Works'},
			{'path': '/blogs', 'name': 'Blog Listing'},
			{'path': '/privacy', 'name': 'Privacy Policy'},
			{'path': '/terms', 'name': 'Terms'},
			{'path': '/help', 'name': 'Help'},
		],
		'admin': {
			'path': '/admin',
			'tabs': [
				'Site Settings',
				'Users',
				'Leads',
				'Blogs',
				'Testimonials',
				'Images',
				'Find & Replace',
				'Dev Manual',
				'Webhook / CRM',
				'AI Content',
				'AI Settings',
				'Business Info',
				'Branding',
				'Content',
				'Email Settings',
			],
		},
		'restricted': ['/dev-admin'],
	}


HARDCODED_SITEMAP = get_sitemap_or_fallback.__wrapped__ if hasattr(get_sitemap_or_fallback, '__wrapped__') else None


def get_github_issues(repo: str = 'Mark0025/wes') -> str:
	"""Pull open issues from GitHub."""
	logger.info(f'Fetching open issues from {repo}...')
	result = subprocess.run(
		['gh', 'issue', 'list', '-R', repo, '--state', 'open', '--limit', '20', '--json', 'number,title,labels'],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		logger.error(f'Failed to fetch issues: {result.stderr}')
		return 'Failed to fetch issues'

	issues = json.loads(result.stdout)
	lines = []
	for issue in issues:
		labels = ', '.join(label['name'] for label in issue.get('labels', []))
		lines.append(f'- #{issue["number"]}: {issue["title"]} [{labels}]')
	logger.success(f'Fetched {len(lines)} open issues')
	return '\n'.join(lines)


def create_browser_session() -> tuple[BrowserSession, str]:
	"""
	Create a BrowserSession using a COPY of the Chrome Default profile.
	Returns (session, tmp_dir) — caller should clean up tmp_dir.
	No need to close Chrome.
	"""
	src_profile = '/Users/markcarpenter/Library/Application Support/Google/Chrome'
	tmp_dir = tempfile.mkdtemp(prefix='browser-use-chrome-')

	logger.info(f'Copying Chrome profile to {tmp_dir}...')
	shutil.copytree(
		f'{src_profile}/Default',
		f'{tmp_dir}/Default',
		dirs_exist_ok=True,
		ignore=shutil.ignore_patterns('Cache', 'Code Cache', 'Service Worker', 'GPUCache', 'DawnCache', 'ShaderCache'),
	)
	shutil.copy2(f'{src_profile}/Local State', f'{tmp_dir}/Local State')
	logger.success('Profile copied.')

	profile = BrowserProfile(
		user_data_dir=tmp_dir,
		profile_directory='Default',
		headless=False,
		disable_security=True,
	)

	return BrowserSession(browser_profile=profile), tmp_dir


def create_llm(model: str = 'sonnet') -> ChatClaudeCode:
	"""Create the ChatClaudeCode LLM instance."""
	return ChatClaudeCode(model=model, timeout=120.0)


def sitemap_prompt_section(sitemap: dict) -> str:
	"""Convert sitemap dict into a prompt section for the agent."""
	lines = ['## Site Map (pre-loaded — skip discovery, go straight to testing)']
	lines.append(f'**BASE URL: {DEV_URL}** — ALL navigation must use this domain.')
	lines.append('')
	lines.append('### Public Pages')
	for page in sitemap.get('public', []):
		lines.append(f'- `{DEV_URL}{page["path"]}` — {page["name"]}')
	lines.append('')
	lines.append(f'### Admin Dashboard ({DEV_URL}/admin)')
	lines.append('Tabs in sidebar: ' + ', '.join(sitemap.get('admin', {}).get('tabs', [])))
	lines.append('')
	lines.append('### RESTRICTED — DO NOT VISIT')
	for r in sitemap.get('restricted', []):
		lines.append(f'- `{DEV_URL}{r}`')
	return '\n'.join(lines)


def human_takeover_prompt() -> str:
	"""Prompt section that tells the agent how to handle human takeover."""
	return """
## Human Takeover Mode
The human may take control of the browser at any time. If you notice:
- The URL changed without you navigating
- New content appeared that you didn't create
- The page is different from what you expected
- DOM elements changed between your steps

Then the HUMAN took over. When this happens:
1. PAUSE and observe what changed
2. LOG what the human did (e.g., "Human navigated to /admin/blogs and clicked on a blog")
3. CONTINUE testing from the new state — don't fight the human's navigation
4. INCLUDE human actions in your report under "HUMAN INTERACTIONS OBSERVED"

This is collaborative testing — the human and AI work together.
"""


def save_report(name: str, report: str) -> Path:
	"""Save a QA report to the reports directory."""
	timestamp = datetime.now().strftime('%Y-%m-%d_%H%M')
	filename = f'{name}_{timestamp}.md'
	path = REPORTS_DIR / filename
	path.write_text(report)
	logger.success(f'Report saved to {path}')
	return path


def create_test_image(path: str = '/tmp/browser-use-test-image.png') -> str:
	"""Create a 100x100 red PNG for upload testing."""
	import struct
	import zlib as _zlib

	width, height = 100, 100
	raw_data = b''
	for y in range(height):
		raw_data += b'\x00'
		for x in range(width):
			raw_data += b'\xff\x00\x00'

	compressed = _zlib.compress(raw_data)

	def chunk(chunk_type: bytes, data: bytes) -> bytes:
		c = chunk_type + data
		crc = struct.pack('>I', _zlib.crc32(c) & 0xFFFFFFFF)
		return struct.pack('>I', len(data)) + c + crc

	png = b'\x89PNG\r\n\x1a\n'
	png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
	png += chunk(b'IDAT', compressed)
	png += chunk(b'IEND', b'')

	Path(path).write_bytes(png)
	logger.info(f'Created test image at {path} ({len(png)} bytes)')
	return path


def cleanup_temp_profiles():
	"""Remove all temporary Chrome profiles."""
	import glob

	for d in glob.glob('/tmp/browser-use-chrome-*'):
		shutil.rmtree(d, ignore_errors=True)
	logger.info('Cleaned up temp Chrome profiles')
