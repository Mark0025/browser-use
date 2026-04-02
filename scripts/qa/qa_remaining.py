"""
Focused test for the 3 remaining untested items + branding re-verify.

Targets ONLY:
  1. Users tab (never clicked due to admin skeleton loading bug)
  2. Preview mode (/preview — never navigated to)
  3. Image upload (file input exists but never tested)
  4. Branding save re-verify (was inconclusive — button stuck on "Saving...")

Closes #10.

Usage:
    cd ~/browser-use
    uv run python scripts/qa/qa_remaining.py
"""

import asyncio
import shutil
import sys

from loguru import logger

from browser_use import Agent

logger.remove()
logger.add(
	sys.stderr, format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>', level='INFO'
)
logger.add('scripts/qa_reports/qa_remaining_{time:YYYY-MM-DD}.log', rotation='10 MB', level='DEBUG')

from shared import (
	DEV_URL,
	cleanup_temp_profiles,
	create_browser_session,
	create_llm,
	create_test_image,
	human_takeover_prompt,
	save_report,
)


async def main():
	test_image = create_test_image()
	llm = create_llm('sonnet')
	session, tmp_dir = create_browser_session()

	task = f"""You are testing 4 SPECIFIC items on dev.fairdealhousebuyer.com that have NEVER been tested.
Do them in order. Budget your steps carefully — you have 15 steps max.

## CRITICAL: ALL URLs use {DEV_URL}

{human_takeover_prompt()}

## CHECKLIST — Test each one, report pass/fail with evidence:

### 1. Users Tab (budget: 3 steps)
- Go to {DEV_URL}/admin
- Click the "Users" tab in the sidebar
- If admin shows skeleton/loading: wait 5 seconds, try clicking again
- Report: what loaded? How many users? What columns are visible? Are there roles/permissions?
- If it stays stuck on skeleton, report that as a finding

### 2. Preview Mode (budget: 3 steps)
- Navigate to {DEV_URL}/preview
- What renders? Is there a preview editor UI?
- Look for pencil/edit icons (relates to Issues #75, #83)
- If there's an edit interface, try clicking one pencil icon — what happens?
- If /preview 404s or redirects, report where it goes

### 3. Image Upload (budget: 4 steps)
- Go to {DEV_URL}/admin → click "Images" tab
- A test image exists at: {test_image}
- Upload it using the file input / upload button
- Did it upload successfully? Does it appear in the image library?
- If yes: delete the test image to clean up
- Report exact success/error messages

### 4. Branding Save Re-verify (budget: 5 steps)
- Go to {DEV_URL}/admin → click "Branding" tab
- Note the current Primary Color value EXACTLY
- Change Primary Color to #00ff00 (green)
- Click "Save Changes"
- Wait 5 seconds — does the button return to "Save Changes" or stay stuck on "Saving..."?
- Navigate away (click another tab like "Users"), then click back to "Branding"
- What is the Primary Color value now? Did #00ff00 persist after navigation?
- If it persisted: open {DEV_URL}/ in a new tab — is the site green?
- REVERT: change Primary Color back to original value, save again
- Confirm revert saved

## RULES
- DO NOT test anything else (blogs, leads, testimonials, etc. are already proven)
- Report EXACT field values and UI text — don't paraphrase
- If something fails, report the EXACT error message
- Clean up all test data (delete uploaded image, revert branding)
- If admin page shows skeleton loading, try waiting 5s + retry ONCE before reporting

## Report Format
For each item, report:
```
### Item N: [Name]
**Status**: PASS / FAIL / INCONCLUSIVE
**Evidence**: [exact values, exact behavior observed]
**Action Taken**: [what you did]
```
"""

	logger.info('Starting remaining-items test (15 max steps)...')

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=session,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	result = await agent.run(max_steps=15)

	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('REMAINING ITEMS TEST REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	save_report('qa_remaining', report)
	shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.warning('Interrupted')
	except Exception as e:
		logger.exception(f'Remaining items test failed: {e}')
	finally:
		cleanup_temp_profiles()
