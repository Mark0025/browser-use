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
logger.add(
	sys.stderr, format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>', level='INFO'
)
logger.add('qa_reports/qa_full_{time:YYYY-MM-DD}.log', rotation='10 MB', level='DEBUG')

from shared import (
	TestResultMemory,
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
	return sitemap


async def main():
	issues = get_github_issues()
	sitemap = await fetch_sitemap_async()
	sitemap_section = sitemap_prompt_section(sitemap)

	llm = create_llm('sonnet')
	session, tmp_dir = create_browser_session()

	# Build admin tabs list for targeted testing
	admin_tabs = sitemap.get('admin', {}).get('tabs', [])
	public_pages = [p['name'] for p in sitemap.get('public', [])]

	# Load test result memory — tracks what's been tested across runs
	memory = TestResultMemory()

	# Ensure all known sections are tracked
	all_sections = (
		[t.lower().replace(' ', '_') for t in admin_tabs]
		+ [p['name'].lower().replace(' ', '_') for p in sitemap.get('public', [])]
		+ ['lead_form', 'preview_mode', 'image_upload']
	)
	memory.ensure_sections_tracked(all_sections)

	# Determine what to test based on memory
	untested = memory.untested_sections()
	failed = memory.failed_sections()
	passed = memory.passed_sections()

	# Map section IDs back to admin tab names for untested tabs
	admin_tab_ids = {t.lower().replace(' ', '_'): t for t in admin_tabs}
	untested_tabs = [admin_tab_ids[sid] for sid in untested if sid in admin_tab_ids]
	failed_tabs = [admin_tab_ids[sid] for sid in failed if sid in admin_tab_ids]

	# Generate the memory-driven prompt section
	memory_prompt = memory.prompt_section()

	task = f"""You are an aggressive QA tester for Fair Deal House Buyer.
Auth: mark@localhousebuyers.net (Google/Clerk — session already active).

## CRITICAL: ALL URLs must use https://dev.fairdealhousebuyer.com (the DEV site)
NEVER navigate to fairdealhousebuyer.com (production). ALWAYS use dev.fairdealhousebuyer.com.
Example: https://dev.fairdealhousebuyer.com/admin (NOT https://fairdealhousebuyer.com/admin)

{sitemap_section}

{human_takeover_prompt()}

## Known Issues
{issues}

{memory_prompt}

## YOUR MISSION — Focus on untested and failed sections:

### Priority 1: Untested Admin Tabs (click each one, interact with everything)
{chr(10).join(f'- **{t}** — click it, report what loads, try every form/button' for t in untested_tabs) if untested_tabs else '- All admin tabs have been tested!'}

{'### Priority 1b: Re-test Failed Admin Tabs' + chr(10) + chr(10).join(f'- **{t}** — previously failed, re-test now' for t in failed_tabs) if failed_tabs else ''}

For EACH tab: click it, scroll through all content, try every button, fill every form, change a value, save, verify.

### Priority 2: Verify Lead in Admin
- Go to admin Leads tab
- Look for any E2E-TEST BrowserUse leads
- Can you see them? Delete them.

### Priority 3: Images — Upload + Edit Test
- Go to Images tab
- Try uploading a small test image
- Try editing an existing image
- Report what happens

### Priority 4: Public Pages Not Yet Tested
- Test any public pages listed as NOT TESTED above
- For each: does it load? What content appears?

### Priority 5: Preview Mode
- Go to /preview — does it load? What does it show?
- Try clicking any pencil/edit icons

## RULES
- DO NOT visit /dev-admin
- Prefix test data with "E2E-BROWSERUSE-TEST"
- Clean up test data (delete what you create)
- Note any `data-source` attributes you see in the DOM
- If you see [ACTION] logs in console, note them
- SKIP sections marked as PASSED unless you have reason to believe they broke

## Report Format
For EACH section you test, clearly state the section name and result:
### SECTION: [section_name]
**STATUS**: PASS / FAIL / PARTIAL
**EVIDENCE**: [what you observed]
**ISSUES**: [any issues found, or "none"]

### SUMMARY
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

	result = await agent.run(max_steps=40)

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

	# Update test result memory from the report
	memory.update_from_report(report, all_sections)
	memory.save()
	logger.info(
		f'Test memory updated: {len(memory.passed_sections())} passed, '
		f'{len(memory.failed_sections())} failed, {len(memory.untested_sections())} untested'
	)

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
