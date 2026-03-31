"""
Multi-Tenant Isolation QA — Prove Company 2 data is separate from Company 1.
Closes #12.

Prerequisite: Company 2 must already exist in the dev-admin dashboard.
Set COMPANY2_SUBDOMAIN env var to the Company 2 subdomain (default: company2).
The script assumes Company 1 is dev.fairdealhousebuyer.com (the existing site).

Usage:
    cd ~/browser-use
    COMPANY2_SUBDOMAIN=company2 uv run python scripts/qa/qa_multi_tenant.py
"""

import asyncio
import os
import shutil
import sys

from loguru import logger

from browser_use import Agent

logger.remove()
logger.add(
	sys.stderr, format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>', level='INFO'
)
logger.add('scripts/qa_reports/qa_multi_tenant_{time:YYYY-MM-DD}.log', rotation='10 MB', level='DEBUG')

from shared import (
	DEV_URL,
	cleanup_temp_profiles,
	create_browser_session,
	create_llm,
	human_takeover_prompt,
	save_report,
)

# Company 2 base URL — configurable via env var
COMPANY2_SUBDOMAIN = os.environ.get('COMPANY2_SUBDOMAIN', 'company2')
# Assumes same domain pattern; adjust if Company 2 uses a different domain
COMPANY2_URL = os.environ.get('COMPANY2_URL', f'https://{COMPANY2_SUBDOMAIN}.dev.fairdealhousebuyer.com')

COMPANY1_URL = DEV_URL  # https://dev.fairdealhousebuyer.com


async def main():
	llm = create_llm('sonnet')
	session, tmp_dir = create_browser_session()

	task = f"""You are testing MULTI-TENANT ISOLATION between two companies on the same platform.

**Company 1 (existing):** {COMPANY1_URL}
**Company 2 (new):** {COMPANY2_URL}

Auth: You are logged in via Chrome profile. You may need to switch between company contexts.
If Company 2 requires separate login, report that as a finding.

{human_takeover_prompt()}

## CRITICAL RULES
- DO NOT visit /dev-admin — it is restricted.
- DO NOT delete or modify Company 1 production data.
- CLEAN UP any test data you create on Company 2.
- Report EXACT values and counts for every check.

---

## TEST PLAN — Multi-Tenant Isolation (11 checks)

### PHASE 1: Data Isolation (5 checks)
Verify Company 2 starts clean — no Company 1 data leaking through.

#### 1. Blogs Isolation
- Navigate to {COMPANY2_URL}/admin → click "Blogs" tab
- Report: How many blogs does Company 2 have?
- Expected: ZERO blogs (Company 1 has 119+)
- **FAIL** if any Company 1 blogs appear
- If admin is not accessible, try {COMPANY2_URL}/blogs (public)
- Report exact count and any blog titles visible

#### 2. Testimonials Isolation
- Go to {COMPANY2_URL}/admin → click "Testimonials" tab
- Report: How many testimonials does Company 2 have?
- Expected: ZERO testimonials
- **FAIL** if Company 1's testimonials appear
- Also check {COMPANY2_URL}/reviews (public)

#### 3. Leads Isolation
- Go to {COMPANY2_URL}/admin → click "Leads" tab
- Report: How many leads does Company 2 have?
- Expected: ZERO leads
- **FAIL** if Company 1's leads appear

#### 4. Business Info Isolation
- Go to {COMPANY2_URL}/admin → click "Business Info" tab
- Report: What are the company name, phone, email, and CEO name?
- Expected: blank or default values
- **FAIL** if Fair Deal House Buyer's info appears (phone, email, CEO name from Company 1)

#### 5. Branding Isolation
- Go to {COMPANY2_URL}/admin → click "Branding" tab
- Report: What is the Primary Color value?
- Expected: default value (not Fair Deal's specific colors)
- **FAIL** if Fair Deal House Buyer's exact brand colors appear

---

### PHASE 2: Cross-Contamination (4 checks)
Create test data on Company 2 and verify it does NOT leak to Company 1.

#### 6. Blog Cross-Contamination
- On {COMPANY2_URL}/admin → "Blogs" tab
- Create a new blog: Title="TENANT-ISO-TEST-BLOG", content="This is a multi-tenant isolation test"
- Save it
- Now go to {COMPANY1_URL}/blogs (Company 1's public blog page)
- Search or scroll — is "TENANT-ISO-TEST-BLOG" visible?
- Expected: NOT visible on Company 1
- **FAIL** if the blog appears on Company 1
- CLEANUP: Go back to {COMPANY2_URL}/admin → Blogs → delete "TENANT-ISO-TEST-BLOG"

#### 7. Testimonial Cross-Contamination
- On {COMPANY2_URL}/admin → "Testimonials" tab
- Create: Name="TENANT-ISO-TESTER", Location="Isolation City", Rating=5, Text="Multi-tenant test review"
- Save it
- Go to {COMPANY1_URL}/reviews (Company 1's public reviews)
- Is "TENANT-ISO-TESTER" visible?
- Expected: NOT visible on Company 1
- **FAIL** if it appears on Company 1
- CLEANUP: Delete the test testimonial from Company 2

#### 8. Lead Cross-Contamination
- Go to {COMPANY2_URL}/ (Company 2's public homepage)
- Fill lead form: First=TENANT-ISO, Last=Test, Address=123 Isolation St, City=TestCity, State=Oklahoma, ZIP=74101, Phone=555-000-1234, Email=tenant-iso@test.com
- Submit the form
- Go to {COMPANY1_URL}/admin → "Leads" tab
- Is "TENANT-ISO" in Company 1's leads?
- Expected: NOT in Company 1's leads
- **FAIL** if it appears in Company 1
- CLEANUP: Go to {COMPANY2_URL}/admin → Leads → delete the test lead

#### 9. Business Info Cross-Contamination
- Go to {COMPANY2_URL}/admin → "Business Info" tab
- Change company name to "TENANT-ISO-COMPANY"
- Save
- Go to {COMPANY1_URL}/ (Company 1's public homepage)
- Is "TENANT-ISO-COMPANY" visible anywhere?
- Expected: NOT visible — Company 1 should still say "Fair Deal House Buyer"
- **FAIL** if Company 1's name changed
- REVERT: Go back to {COMPANY2_URL}/admin → Business Info → clear the name or set back to original, save

---

### PHASE 3: Auth Isolation (2 checks)

#### 10. Users Isolation
- Go to {COMPANY2_URL}/admin → "Users" tab
- Report: What users are listed?
- Expected: Only Company 2 users (or empty)
- **FAIL** if Company 1's users (e.g. mark@localhousebuyers.net) appear in Company 2

#### 11. Settings Isolation
- Go to {COMPANY2_URL}/admin → "Site Settings" tab
- Report: What settings are visible?
- Expected: Company 2 specific settings or defaults
- Go to {COMPANY2_URL}/admin → "Webhook / CRM" tab
- Report: What webhook URL is configured?
- **FAIL** if Company 1's Zapier webhook URL appears
- **FAIL** if Company 1's domain or company-specific config appears

---

## KNOWN RISKS TO CHECK (from codebase audit)
- `site-config.json` is a global fallback — Company 2 might inherit Company 1 defaults
- Images are in a shared Docker volume — check if Company 2 sees Company 1's uploaded images
- Webhook URL may be global — Company 2 leads might route to Company 1's Zapier

## BONUS CHECK (if time permits)
- Go to {COMPANY2_URL}/admin → "Images" tab
- Report: Are Company 1's images visible? How many images shown?
- Expected: ZERO images (or only Company 2's)

---

## REPORT FORMAT

For EACH item report:
```
### Check N: [Name]
**Status**: PASS / FAIL / BLOCKED / PARTIAL
**Evidence**: [exact values, counts, what you saw]
**Action Taken**: [what you did]
**Cleanup**: [what test data was removed, or N/A]
```

If any check is BLOCKED (e.g. Company 2 doesn't exist, admin not accessible), report:
- What URL you tried
- What error/page appeared
- What needs to happen to unblock

At the end, include:
### MULTI-TENANT ISOLATION SUMMARY
- Total checks: X/11
- PASS: X
- FAIL: X (list which ones)
- BLOCKED: X (list which ones)
- Known risk findings: [list any of the 3 known risks confirmed]
- Test data cleanup: [confirm all test data removed]
- Overall verdict: ISOLATED / NOT ISOLATED / INCONCLUSIVE

## RULES
- DO NOT visit /dev-admin
- CLEAN UP all test data created during testing
- Report EXACT field values and counts
- If Company 2 URL doesn't resolve, report BLOCKED immediately
- If you can't log into Company 2's admin, report BLOCKED and try public pages only
"""

	logger.info(f'Starting multi-tenant isolation QA — Company 1: {COMPANY1_URL}, Company 2: {COMPANY2_URL}')
	logger.info('11 isolation checks, 40 max steps...')

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

	report_lines = []
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						report_lines.append(r.extracted_content)

	report = '\n'.join(report_lines)

	print('\n' + '=' * 80)
	print('MULTI-TENANT ISOLATION QA REPORT')
	print('=' * 80)
	print(report)
	print('=' * 80)

	save_report('qa_multi_tenant', report)
	shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.warning('Interrupted')
	except Exception as e:
		logger.exception(f'Multi-tenant isolation QA failed: {e}')
	finally:
		cleanup_temp_profiles()
