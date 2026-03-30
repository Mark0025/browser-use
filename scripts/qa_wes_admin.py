"""
AI QA Tester for wes Admin Dashboard (Fair Deal House Buyer)

Uses browser-use + ChatClaudeCode with your Chrome profile (mark@localhousebuyers.net)
to log in via Clerk/Google and inspect the admin dashboard.

Usage:
    cd ~/browser-use
    uv run python scripts/qa_wes_admin.py
"""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile

from loguru import logger

from browser_use import Agent, BrowserProfile, BrowserSession
from browser_use.llm.claude_code.chat import ChatClaudeCode

# Configure loguru
logger.remove()  # Remove default handler
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
logger.add("qa_wes_admin_{time:YYYY-MM-DD}.log", rotation="10 MB", level="DEBUG")


def get_github_issues() -> str:
	"""Pull open issues from Mark0025/wes."""
	logger.info("Fetching open issues from Mark0025/wes...")
	result = subprocess.run(
		['gh', 'issue', 'list', '-R', 'Mark0025/wes', '--state', 'open', '--limit', '20', '--json', 'number,title,labels'],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		logger.error(f"Failed to fetch issues: {result.stderr}")
		return 'Failed to fetch issues'

	issues = json.loads(result.stdout)
	lines = []
	for issue in issues:
		labels = ', '.join(l['name'] for l in issue.get('labels', []))
		lines.append(f"- #{issue['number']}: {issue['title']} [{labels}]")
	logger.success(f"Fetched {len(lines)} open issues")
	return '\n'.join(lines)


async def main():
	issues = get_github_issues()

	logger.info("Initializing ChatClaudeCode (sonnet, via SDK)...")
	llm = ChatClaudeCode(model='sonnet', timeout=120.0)

	# Copy Chrome profile to temp dir so we don't conflict with running Chrome
	src_profile = '/Users/markcarpenter/Library/Application Support/Google/Chrome'
	tmp_dir = tempfile.mkdtemp(prefix='browser-use-chrome-')
	logger.info(f"Copying Chrome profile to {tmp_dir}...")
	shutil.copytree(f'{src_profile}/Default', f'{tmp_dir}/Default', dirs_exist_ok=True,
		ignore=shutil.ignore_patterns('Cache', 'Code Cache', 'Service Worker', 'GPUCache', 'DawnCache', 'ShaderCache'))
	shutil.copy2(f'{src_profile}/Local State', f'{tmp_dir}/Local State')
	logger.success("Profile copied. Launching browser...")

	profile = BrowserProfile(
		user_data_dir=tmp_dir,
		profile_directory='Default',
		headless=False,
		disable_security=True,
	)

	session = BrowserSession(browser_profile=profile)

	task = f"""You are an aggressive QA tester for the Fair Deal House Buyer website.
You are logged in as mark@localhousebuyers.net via Google/Clerk.
Test EVERYTHING like a mad man. Click every button, fill every form, try to break things.

## CRITICAL: DO NOT visit /dev-admin — that route is restricted and will break. Stay away from it.

## Your Mission — Test EVERYTHING Else

### Phase 1: Authentication
1. Go to https://dev.fairdealhousebuyer.com/admin
2. If you see a login/sign-in page, click "Continue with Google" — your Google session is already active
3. Once logged in, note what admin sections are available

### Phase 2: Admin Dashboard — Click EVERYTHING
4. Click every single link, button, and tab in the admin sidebar
5. For each admin section:
   - Does it load?
   - Any errors or blank screens?
   - Can you interact with forms/buttons?
   - What data is shown?

### Phase 3: Aggressive Testing — Try to Break Things
6. BLOGS — FULL CRUD CYCLE:
   a. Create a blog (title: "E2E-BROWSERUSE-TEST Blog", body: "This is a test blog post created by browser-use QA")
   b. Save it as draft
   c. Check if it appears in the blog list
   d. Edit it — change the title to "E2E-BROWSERUSE-TEST Blog EDITED"
   e. Publish it
   f. Go to the PUBLIC site /blogs and verify it appears
   g. Go back to admin, delete it
   h. Verify it's gone from public /blogs
7. TESTIMONIALS — FULL CRUD CYCLE:
   a. View all testimonials
   b. Create one (name: "E2E-BROWSERUSE-TEST Reviewer", rating: 5, text: "Test testimonial from browser-use QA")
   c. Save it, check if preview button exists (Issue #84)
   d. Go to public /reviews and check if it shows
   e. Go back to admin, delete it
8. SETTINGS — CHANGE AND REVERT:
   a. Open every settings panel
   b. Note current values
   c. Change something small (like a phone number or company name)
   d. Save it
   e. Check the public site — did it update?
   f. REVERT it back to the original value and save
9. IMAGES: Try uploading or editing an image (Issue #85 — may throw server error)
10. LEAD FORM — SUBMIT AND VERIFY:
    a. Go to public homepage
    b. Fill lead form: First=E2E-TEST, Last=BrowserUse, Address=123 Test St, City=Oklahoma City, State=Oklahoma, ZIP=73101, Phone=555-000-1234, Email=e2e-browseruse@test.com
    c. Submit it
    d. Check if you get a confirmation
    e. Go to admin — can you see the submitted lead?
11. NAVIGATION: Click every nav link on public AND admin pages — do any 404?
12. PREVIEW MODE: Try to enter preview/edit mode on a public page (Issue #75, #83) — if there's a pencil icon or edit button, click it

### Phase 4: Public Pages — Interact With Everything
13. Go to /reviews — click any interactive elements
14. Go to /about — try all links
15. Go to /how-it-works — try all links
16. Go to /blogs — click into individual blog posts
17. Check /privacy-policy and /terms — do they load?

### Phase 5: Cross-Reference Known Issues
{issues}

## IMPORTANT RULES
- DO NOT visit /dev-admin (restricted, will error)
- DO prefix any test content with "E2E-BROWSERUSE-TEST" so it can be found/deleted
- BE AGGRESSIVE — click everything, scroll everywhere, try edge cases
- If something errors, note the exact error message

## Output Format
Provide a comprehensive QA report:

### ADMIN SECTIONS FOUND
- List every admin section/page discovered

### WORKING (things confirmed functional)
- Numbered list

### BROKEN (things that error or don't work)
- Numbered list with GitHub issue # if applicable

### NEW ISSUES (not tracked in GitHub)
- Numbered list with detailed description

### EDGE CASES TESTED
- What unusual things you tried and results

### OVERALL SCORE
- Score out of 10
- Summary paragraph
"""

	logger.info("Creating browser-use Agent (30 max steps, vision=True)...")
	agent = Agent(
		task=task,
		llm=llm,
		browser_session=session,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	logger.info("Starting QA run...")
	result = await agent.run(max_steps=30)

	# Print the final report
	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('ADMIN QA REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	# Also save to file
	with open('qa_wes_admin_report.md', 'w') as f:
		f.write(report)
	logger.success("Report saved to qa_wes_admin_report.md")


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.warning("Interrupted by user")
	except Exception as e:
		logger.exception(f"QA run failed: {e}")
	finally:
		import glob
		for d in glob.glob('/tmp/browser-use-chrome-*'):
			shutil.rmtree(d, ignore_errors=True)
		logger.info("Cleaned up temp Chrome profiles")
