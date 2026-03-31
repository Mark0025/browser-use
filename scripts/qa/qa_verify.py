"""
Final verification pass — close ALL coverage gaps.

Tests ONLY what previous runs did NOT cover or left unverified.
Closes #7, #9.

Usage:
    cd ~/browser-use
    uv run python scripts/qa/qa_verify.py
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
logger.add('scripts/qa_reports/qa_verify_{time:YYYY-MM-DD}.log', rotation='10 MB', level='DEBUG')

from shared import (
	TestResultMemory,
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

	# Load test result memory to show the agent what's already been tested
	memory = TestResultMemory()
	memory_prompt = memory.prompt_section()

	# Sections this script covers
	verify_sections = [
		'email_settings',
		'branding',
		'users',
		'privacy',
		'terms',
		'blogs',
		'preview_mode',
		'lead_form',
		'image_upload',
	]
	memory.ensure_sections_tracked(verify_sections)

	task = f"""You are doing a FINAL VERIFICATION pass on dev.fairdealhousebuyer.com.
Focus on items that have NOT been tested or previously FAILED.

{memory_prompt}

## CRITICAL: ALL URLs use https://dev.fairdealhousebuyer.com

{human_takeover_prompt()}

## VERIFICATION CHECKLIST — Test each one, report pass/fail with evidence:

### 1. Email Reply-To Field (is it a bug or user data?)
- Go to https://dev.fairdealhousebuyer.com/admin
- Click "Email Settings" tab
- READ the Reply-To Email field value — what does it say EXACTLY?
- If it has a typo (double 'b' in 'housebbuyers'), change it to: info@fairdealhousebuyers.com
- Click Save Changes
- Report: was it a typo or correct?

### 2. Branding Save (is it actually broken?)
- Click "Branding" tab
- Note the current Primary Color value
- Change it to #00ff00 (green)
- Click "Save Changes"
- Wait 5 seconds
- Does the button return to "Save Changes" or stay stuck on "Saving..."?
- RELOAD the page (navigate away then back to Branding)
- What is the Primary Color now? Did it save?
- If it saved: check https://dev.fairdealhousebuyer.com/ — did the color change on the public site?
- REVERT: change Primary Color back to whatever it was originally, save again

### 3. Users Tab
- Click "Users" tab
- What loads? How many users? What columns? Can you see roles?
- Report everything visible

### 4. Public Pages — Just Load Them
- Navigate to https://dev.fairdealhousebuyer.com/privacy — does it render? What content?
- Navigate to https://dev.fairdealhousebuyer.com/terms — does it render? What content?
- Navigate to https://dev.fairdealhousebuyer.com/blogs — click on the FIRST blog post title
- Does the individual blog page render? What's the title and content?

### 5. Preview Mode
- Navigate to https://dev.fairdealhousebuyer.com/preview
- What shows? Is there a preview editor? Pencil icons?
- If there's an edit interface, try clicking something
- Report what you see (relates to Issues #75, #83)

### 6. Lead Form → Admin Verification (complete the loop)
- Go to https://dev.fairdealhousebuyer.com/
- Fill lead form: First=VERIFY-TEST, Last=Final, Address=999 Verify St, City=Tulsa, State=Oklahoma, ZIP=74101, Phone=555-999-0000, Email=verify@test.com
- Submit it
- Go to https://dev.fairdealhousebuyer.com/admin → click "Leads" tab
- Is the VERIFY-TEST lead there?
- DELETE it to clean up

### 7. Image Upload
- Go to admin → "Images" tab
- A test image exists at {test_image}
- Try uploading it using the file input
- Did it upload? Does it appear in the library?
- If yes, delete it to clean up

## RULES
- DO NOT test anything already proven (blogs, business info, testimonials, site settings)
- Report EXACT field values — don't paraphrase
- If something fails, report the exact error
- Clean up all test data

## Report Format
For each item, report:
```
### Item N: [Name]
**Status**: PASS / FAIL / INCONCLUSIVE
**Evidence**: [exact values, exact behavior observed]
**Action Taken**: [what you did]
```
"""

	logger.info('Starting final verification pass (20 max steps)...')

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=session,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	result = await agent.run(max_steps=20)

	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('VERIFICATION REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	save_report('qa_verify', report)

	# Update test result memory from the report
	memory.update_from_report(report, verify_sections)
	memory.save()
	logger.info(
		f'Test memory updated: {len(memory.passed_sections())} passed, '
		f'{len(memory.failed_sections())} failed, {len(memory.untested_sections())} untested'
	)

	shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.warning('Interrupted')
	except Exception as e:
		logger.exception(f'Verification failed: {e}')
	finally:
		cleanup_temp_profiles()
