"""
FINAL QA — Test every remaining untested route and workflow.
Closes #10. Uses successful log patterns as context for the agent.

Usage:
    cd ~/browser-use
    uv run python scripts/qa/qa_final.py
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
logger.add('scripts/qa_reports/qa_final_{time:YYYY-MM-DD}.log', rotation='10 MB', level='DEBUG')

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

	# Load test result memory
	memory = TestResultMemory()
	final_sections = [
		'users',
		'branding',
		'help',
		'sign_in',
		'sign_up',
		'preview_mode',
		'preview_about',
		'preview_how_it_works',
		'preview_blogs',
		'preview_blog_detail',
		'dev_manual',
		'lead_form',
		'image_upload',
		'blog_detail_lead_form',
		'404_page',
	]
	memory.ensure_sections_tracked(final_sections)
	memory_prompt = memory.prompt_section()

	task = f"""You are doing the FINAL QA pass on https://dev.fairdealhousebuyer.com.
You must test every item below. No exceptions. Auth: mark@localhousebuyers.net (already logged in via Chrome profile).

{memory_prompt}

## CRITICAL: ALL URLs use https://dev.fairdealhousebuyer.com
## DO NOT visit /dev-admin — it is restricted.

{human_takeover_prompt()}

## PROVEN PATTERNS (from 6 previous successful runs — use these):

### Admin Navigation
- Go to https://dev.fairdealhousebuyer.com/admin
- Sidebar buttons: click by text "Users", "Branding", "Images", etc.
- data-testid selectors: admin-tab-users, admin-tab-branding, admin-tab-images, etc.
- Save button: data-testid="admin-save-changes-btn" or text "Save Changes"
- After save: button shows "Saving..." then returns to "Save Changes" + toast notification

### Forms
- Testimonial create: "Add Testimonial" → fill name/location/rating/text → Save
- Rating combobox: use select_dropdown with text "5 Stars"
- Lead form (public): shadow DOM inputs — fill First, Last, Street Address, City, State, ZIP, Phone, Email
- Lead submit: button "Get My Cash Offer Now" → shows "Processing..."

---

## TEST CHECKLIST — Do each one in order:

### 1. Admin → Users Tab
- Go to https://dev.fairdealhousebuyer.com/admin
- Click "Users" tab
- Report: how many users? What columns? Any role management UI?
- DO NOT change any user roles

### 2. Admin → Branding (RE-VERIFY)
- Click "Branding" tab
- READ and report current Primary Color value exactly
- Change Primary Color to #00ff00 (green)
- Click "Save Changes"
- Wait 5 seconds — does button return to normal or stay stuck on "Saving..."?
- Navigate away (click "Content" tab) then back to "Branding"
- READ Primary Color again — is it #00ff00 (saved) or original (not saved)?
- Open https://dev.fairdealhousebuyer.com/ in new tab — any visible green?
- REVERT: change Primary Color back to whatever the original was, save again

### 3. Public → /help
- Navigate to https://dev.fairdealhousebuyer.com/help
- Does it load? What content shows?

### 4. Public → /sign-in
- Navigate to https://dev.fairdealhousebuyer.com/sign-in
- Does Clerk sign-in page render?

### 5. Public → /sign-up
- Navigate to https://dev.fairdealhousebuyer.com/sign-up
- Does Clerk sign-up page render?

### 6. Preview Mode → /preview
- Navigate to https://dev.fairdealhousebuyer.com/preview
- What loads? Is there an editor sidebar? Pencil icons?
- If editable elements exist, click one — what happens?

### 7. Preview → /preview/about
- Navigate to https://dev.fairdealhousebuyer.com/preview/about
- Does the preview about page load?

### 8. Preview → /preview/how-it-works
- Navigate to https://dev.fairdealhousebuyer.com/preview/how-it-works
- Does the preview how-it-works page load?

### 9. Preview → /preview/blogs
- Navigate to https://dev.fairdealhousebuyer.com/preview/blogs
- Does the preview blog listing load?

### 10. Preview → /preview/blogs/:slug
- If blogs loaded in step 9, click into one
- Does the preview blog detail page render?

### 11. Dev Manual Page
- Navigate to https://dev.fairdealhousebuyer.com/dev-man
- Does it load? What content?

### 12. Lead Form → Admin Verification Loop
- Go to https://dev.fairdealhousebuyer.com/
- Fill lead form: First=FINAL-VERIFY, Last=Test, Address=999 Final St, City=Tulsa, State=Oklahoma, ZIP=74101, Phone=555-888-0000, Email=final-verify@test.com
- Click "Get My Cash Offer Now"
- Wait for confirmation
- Go to https://dev.fairdealhousebuyer.com/admin → click "Leads" tab
- Is "FINAL-VERIFY" in the leads list?
- DELETE it to clean up

### 13. Image Upload
- Go to admin → click "Images" tab
- A test image exists at {test_image}
- Find the file upload input and upload this image
- Does it appear in the library?
- If yes, DELETE it to clean up

### 14. Blog Detail → Lead Form
- Go to https://dev.fairdealhousebuyer.com/blogs
- Click into the first blog post
- Scroll to bottom — is there a lead form?
- Does the form render correctly?

### 15. 404 Page
- Navigate to https://dev.fairdealhousebuyer.com/this-page-does-not-exist
- Does a proper 404 page show? Or does it crash?

---

## REPORT FORMAT

For EACH item report:
```
### Item N: [Name]
**Status**: PASS / FAIL / PARTIAL
**Evidence**: [exact values, exact behavior]
**Action Taken**: [what you did]
```

At the end, include:
### FINAL COVERAGE SUMMARY
- Total items tested: X/15
- Total PASS: X
- Total FAIL: X
- Total PARTIAL: X
- Any test data left behind? (should be none)

## RULES
- DO NOT visit /dev-admin
- Clean up ALL test data (leads, images, branding reverts)
- Report EXACT field values
- If something fails, report the exact error message
"""

	logger.info('Starting FINAL QA pass — 15 items, 35 max steps...')

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=session,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	result = await agent.run(max_steps=35)

	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('FINAL QA REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	save_report('qa_final', report)

	# Update test result memory from the report
	memory.update_from_report(report, final_sections)
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
		logger.exception(f'Final QA failed: {e}')
	finally:
		cleanup_temp_profiles()
