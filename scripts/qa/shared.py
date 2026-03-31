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
from datetime import datetime
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


async def fetch_sitemap() -> dict | None:
	"""Fetch the dev sitemap from /api/dev/sitemap. Returns None if not available."""
	try:
		async with httpx.AsyncClient(verify=False, timeout=10) as client:
			resp = await client.get(f'{DEV_URL}/api/dev/sitemap')
			if resp.status_code == 200:
				data = resp.json()
				logger.success(f"Fetched sitemap: {len(data.get('public', []))} public, {len(data.get('admin', {}).get('tabs', []))} admin tabs")
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
				'Site Settings', 'Users', 'Leads', 'Blogs', 'Testimonials', 'Images',
				'Find & Replace', 'Dev Manual', 'Webhook / CRM', 'AI Content',
				'AI Settings', 'Business Info', 'Branding', 'Content', 'Email Settings',
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
		labels = ', '.join(l['name'] for l in issue.get('labels', []))
		lines.append(f"- #{issue['number']}: {issue['title']} [{labels}]")
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
		lines.append(f"- `{DEV_URL}{page['path']}` — {page['name']}")
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
		crc = struct.pack('>I', _zlib.crc32(c) & 0xffffffff)
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
