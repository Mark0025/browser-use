"""
Full QA test — fetches sitemap, skips discovery, tests everything.
Uses pre-loaded sitemap from /api/dev/sitemap + human takeover support.

Usage:
    cd ~/browser-use
    uv run python scripts/qa/qa_full.py
"""

import asyncio
import shutil
import sys

from loguru import logger

from browser_use import Agent

# Configure loguru
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
logger.add("qa_reports/qa_full_{time:YYYY-MM-DD}.log", rotation="10 MB", level="DEBUG")

from shared import (
	DEV_URL,
	cleanup_temp_profiles,
	create_browser_session,
	create_llm,
	get_github_issues,
	human_takeover_prompt,
	save_report,
	sitemap_prompt_section,
)


async def fetch_sitemap_async() -> dict:
	"""Fetch sitemap with fallback."""
	from shared import fetch_sitemap
	sitemap = await fetch_sitemap()
	if not sitemap:
		from shared import get_sitemap_or_fallback
		logger.warning('Using hardcoded sitemap fallback')
		return {
			'public': [
				{'path': '/', 'name': 'Homepage'},
				{'path': '/reviews', 'name': 'Reviews'},
				{'path': '/about', 'name': 'About'},
				{'path': '/how-it-works', 'name': 'How It Works'},
				{'path': '/blogs', 'name': 'Blog Listing'},
				{'path': '/privacy', 'name': 'Privacy Policy'},
				{'path': '/terms', 'name': 'Terms'},
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
	return sitemap


async def main():
	issues = get_github_issues()
	sitemap = await fetch_sitemap_async()
	sitemap_section = sitemap_prompt_section(sitemap)

	llm = create_llm('sonnet')
	session, tmp_dir = create_browser_session()

	# Build admin tabs list for targeted testing
	admin_tabs = sitemap.get('admin', {}).get('tabs', [])
	already_tested = ['Blogs']  # From previous run — skip these

	untested_tabs = [t for t in admin_tabs if t not in already_tested]

	task = f"""You are an aggressive QA tester for Fair Deal House Buyer.
Auth: mark@localhousebuyers.net (Google/Clerk — session already active).

{sitemap_section}

{human_takeover_prompt()}

## Known Issues
{issues}

## PREVIOUSLY TESTED (skip unless you see something broken):
- Blog CRUD: ✅ PASSED (create, edit, publish, verify public, delete — all work)
- Public /reviews: Found issues (E2E test data, missing stats, dual copyright)
- Public homepage: ✅ Navigation, hero, lead forms work
- Public /about: ⚠️ Loading flash (FOUC)
- Public /how-it-works: ✅ Works

## YOUR MISSION — Test what was NOT tested last time:

### Priority 1: Admin Sections (UNTESTED)
Click each of these admin tabs and test thoroughly:
{chr(10).join(f'- {t}' for t in untested_tabs)}

For each tab:
1. Click it — does it load?
2. What data/forms/buttons are visible?
3. Try interacting with forms — change a value, save, verify
4. Look for `data-source` attributes in the DOM (tells you what server action feeds this component)

### Priority 2: Testimonial CRUD
- Create testimonial: name="E2E-BROWSERUSE-TEST", rating=5, text="Test from browser-use"
- Check if preview button exists (Issue #84)
- Go to public /reviews — does it show?
- Delete it from admin

### Priority 3: Settings Change + Revert
- Go to Business Info or Branding
- Note current phone number
- Change it to "555-BROWSER-USE-TEST"
- Save, check public site footer — did it update?
- REVERT to original, save again

### Priority 4: Lead Form Submission
- Go to public homepage
- Fill lead form: First=E2E-TEST, Last=BrowserUse, Address=123 Test St, City=Oklahoma City, State=Oklahoma, ZIP=73101, Phone=555-000-1234, Email=e2e@test.com
- Submit — what happens?
- Go to admin Leads tab — is it there?

### Priority 5: Remaining Public Pages
- /privacy — does it load?
- /terms — does it load?
- /help — does it load?
- /blogs — click into a blog post, does it render?

## RULES
- DO NOT visit /dev-admin
- Prefix test data with "E2E-BROWSERUSE-TEST"
- Clean up test data (delete what you create)
- Note any `data-source` attributes you see in the DOM
- If you see [ACTION] logs in console, note them

## Report Format
### ADMIN SECTIONS TESTED
### WORKING
### BROKEN (with issue # if applicable)
### NEW ISSUES
### DATA SOURCES OBSERVED (data-source attributes found)
### HUMAN INTERACTIONS OBSERVED (if any)
### OVERALL SCORE (/10)
"""

	logger.info(f'Starting QA with {len(untested_tabs)} untested admin tabs...')

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=session,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	result = await agent.run(max_steps=30)

	# Extract report
	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('QA REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	save_report('qa_full', report)

	# Cleanup
	shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.warning('Interrupted by user')
	except Exception as e:
		logger.exception(f'QA run failed: {e}')
	finally:
		cleanup_temp_profiles()
