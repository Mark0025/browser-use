"""Tests for QA report parsing and GitHub issue creation logic."""

import sys
from pathlib import Path

# Add scripts/qa to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts' / 'qa'))

from github_issues import _normalize_title, _truncate, parse_report_findings

SAMPLE_REPORT_WITH_NEW_ISSUES = """
# QA REPORT

### WORKING
- Homepage loads
- Blog listing works

### BROKEN
- Image upload throws 500 error on save
- Testimonial delete button missing (#84)

### NEW ISSUES
- /help returns 404 — route not implemented
- Blog detail pages have no inline lead form, only a CTA button link
- Branding primary color does not visually apply to CTA buttons on public site

### OVERALL SCORE
7/10
"""

SAMPLE_REPORT_WITH_ITEM_BLOCKS = """
### Item 3: Public /help page
**Status**: FAIL
**Evidence**: Page returned '404 This page could not be found.' — /help route does not exist.
**Action Taken**: Navigated to https://dev.fairdealhousebuyer.com/help.

---

### Item 4: Sign-in redirect
**Status**: PASS (with note)
**Evidence**: Navigating to /sign-in redirected to /admin.
**Action Taken**: Navigated to /sign-in, observed redirect.

---

### Item 13: Image Upload
**Status**: FAIL
**Evidence**: Upload button threw a 500 server error when clicking save.
**Action Taken**: Went to admin Images tab, selected file, clicked upload.
"""

SAMPLE_REPORT_WITH_KEY_FINDINGS = """
## KEY FINDINGS
1. **/help returns 404** — Route not implemented
2. **Blog detail pages have no inline lead form** — Only a CTA button
3. **Branding save/persistence works correctly** — Color saves and persists
4. **Lead form pipeline works end-to-end** — Submit → appears in admin
"""

EMPTY_REPORT = """
# QA REPORT

### WORKING
- Everything works great

### OVERALL SCORE
10/10
"""


def test_parse_new_issues_section():
	findings = parse_report_findings(SAMPLE_REPORT_WITH_NEW_ISSUES)
	titles = [f.title for f in findings]

	# Should find the 3 NEW ISSUES items
	assert any('/help returns 404' in t for t in titles)
	assert any('lead form' in t.lower() for t in titles)
	assert any('branding' in t.lower() or 'color' in t.lower() for t in titles)

	# Should find the BROKEN item without issue reference (image upload)
	assert any('image upload' in t.lower() for t in titles)

	# Should NOT include the BROKEN item that references #84 (already tracked)
	assert not any('#84' in t for t in titles)

	# All NEW ISSUES findings should have status 'NEW'
	new_findings = [f for f in findings if f.section == 'NEW ISSUES']
	assert len(new_findings) == 3
	for f in new_findings:
		assert f.status == 'NEW'


def test_parse_item_blocks_fail_only():
	findings = parse_report_findings(SAMPLE_REPORT_WITH_ITEM_BLOCKS)
	titles = [f.title for f in findings]

	# Should find FAIL items only
	assert any('/help' in t.lower() for t in titles)
	assert any('image upload' in t.lower() for t in titles)

	# Should NOT include PASS items
	assert not any('sign-in' in t.lower() for t in titles)

	# Check evidence and steps are extracted
	help_finding = next(f for f in findings if '/help' in f.title.lower())
	assert '404' in help_finding.evidence


def test_parse_key_findings_failures_only():
	findings = parse_report_findings(SAMPLE_REPORT_WITH_KEY_FINDINGS)
	titles = [f.title for f in findings]

	# Should find failure-indicating findings
	assert any('404' in t for t in titles)

	# Should NOT include positive findings
	assert not any('works correctly' in t for t in titles)
	assert not any('end-to-end' in t.lower() for t in titles)


def test_empty_report_returns_nothing():
	findings = parse_report_findings(EMPTY_REPORT)
	assert findings == []


def test_deduplication_across_sections():
	"""Same finding in NEW ISSUES and KEY FINDINGS should not produce duplicates."""
	report = """
### NEW ISSUES
- /help returns 404 — route not implemented

## KEY FINDINGS
1. **/help returns 404** — Route not implemented
"""
	findings = parse_report_findings(report)
	help_findings = [f for f in findings if '404' in f.title]
	assert len(help_findings) == 1


def test_truncate():
	assert _truncate('short', 120) == 'short'
	assert _truncate('a' * 200, 120) == 'a' * 117 + '...'
	assert _truncate('**bold text**', 120) == 'bold text'


def test_normalize_title():
	assert _normalize_title('  /help Returns 404!!  ') == 'help returns 404'
	assert _normalize_title('[browser-use QA] Something') == 'browser use qa something'


def test_parse_real_report_file():
	"""Parse the actual report file from the repo if it exists."""
	report_path = Path(__file__).parent.parent.parent / 'scripts' / 'qa_reports' / 'qa_final_2026-03-30_2353.md'
	if not report_path.exists():
		return  # skip if report not present

	report = report_path.read_text()
	findings = parse_report_findings(report)

	# The real report has at least the /help 404 failure
	titles_lower = [f.title.lower() for f in findings]
	assert any('help' in t and '404' in t for t in titles_lower)
