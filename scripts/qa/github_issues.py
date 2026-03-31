"""
Auto-create GitHub issues from QA report findings.

Parses the "NEW ISSUES", "BROKEN", and "KEY FINDINGS" sections of QA reports
and creates GitHub issues on the target repo with deduplication.

Usage (standalone):
    uv run python scripts/qa/github_issues.py scripts/qa_reports/qa_full_2026-03-30_2001.md

Usage (from QA scripts):
    from github_issues import create_issues_from_report
    created = await create_issues_from_report(report_text)
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger


@dataclass
class QAFinding:
	"""A single finding extracted from a QA report."""

	title: str
	body: str
	status: str = 'FAIL'  # FAIL, BROKEN, NEW
	section: str = ''  # which report section it came from
	evidence: str = ''
	steps: str = ''


def parse_report_findings(report: str) -> list[QAFinding]:
	"""
	Parse a QA report and extract actionable findings (failures, broken items, new issues).

	Looks for these sections:
	- "### NEW ISSUES" — explicitly flagged new issues
	- "### BROKEN" — broken items with optional issue references
	- "### Item N: ..." blocks with Status: FAIL
	- "## KEY FINDINGS" — numbered findings that indicate failures
	"""
	findings: list[QAFinding] = []

	# Strategy 1: Extract from "### NEW ISSUES" section
	new_issues_match = re.search(
		r'###?\s*NEW\s+ISSUES\s*\n(.*?)(?=\n###?\s|\n---|\n##\s|$)',
		report,
		re.DOTALL | re.IGNORECASE,
	)
	if new_issues_match:
		section_text = new_issues_match.group(1).strip()
		for line in section_text.split('\n'):
			line = line.strip()
			if not line or line.startswith('#'):
				continue
			# Strip leading bullet/dash/number
			line = re.sub(r'^[-*•]\s*', '', line)
			line = re.sub(r'^\d+\.\s*', '', line)
			if len(line) > 10:  # skip trivially short lines
				findings.append(QAFinding(
					title=_truncate(line, 120),
					body=line,
					status='NEW',
					section='NEW ISSUES',
				))

	# Strategy 2: Extract from "### BROKEN" section
	broken_match = re.search(
		r'###?\s*BROKEN\s*(?:\(.*?\))?\s*\n(.*?)(?=\n###?\s|\n---|\n##\s|$)',
		report,
		re.DOTALL | re.IGNORECASE,
	)
	if broken_match:
		section_text = broken_match.group(1).strip()
		for line in section_text.split('\n'):
			line = line.strip()
			if not line or line.startswith('#'):
				continue
			line = re.sub(r'^[-*•]\s*', '', line)
			line = re.sub(r'^\d+\.\s*', '', line)
			# Skip lines that already reference a known issue number
			if re.search(r'#\d+', line):
				continue  # already tracked
			if len(line) > 10:
				findings.append(QAFinding(
					title=_truncate(line, 120),
					body=line,
					status='BROKEN',
					section='BROKEN',
				))

	# Strategy 3: Extract from "### Item N:" blocks with FAIL status
	# Split report into item blocks first, then parse each independently
	item_block_pattern = re.compile(r'(###\s*Item\s+\d+:\s*.+?)(?=\n###\s*Item\s+\d+:|\n---|\Z)', re.DOTALL)
	for block_match in item_block_pattern.finditer(report):
		block = block_match.group(1)
		title_match = re.match(r'###\s*Item\s+\d+:\s*(.+)', block)
		status_match = re.search(r'\*\*Status\*\*:\s*(FAIL\b[^\n]*)', block)
		if not title_match or not status_match:
			continue

		item_title = title_match.group(1).strip()
		status = status_match.group(1).strip()
		evidence = ''
		evidence_match = re.search(r'\*\*Evidence\*\*:\s*([^\n]*(?:\n(?!\*\*)[^\n]*)*)', block)
		if evidence_match:
			evidence = evidence_match.group(1).strip()
		steps = ''
		action_match = re.search(r'\*\*Action Taken\*\*:\s*([^\n]*)', block)
		if action_match:
			steps = action_match.group(1).strip()

		body_lines = [f'**Status**: {status}', f'**Evidence**: {evidence}']
		if steps:
			body_lines.append(f'**Steps**: {steps}')

		findings.append(QAFinding(
			title=item_title,
			body='\n'.join(body_lines),
			status='FAIL',
			section='Item Block',
			evidence=evidence,
			steps=steps,
		))

	# Strategy 4: Extract from "## KEY FINDINGS" numbered list (only failure-indicating ones)
	key_findings_match = re.search(
		r'##\s*KEY\s+FINDINGS\s*\n(.*?)(?=\n##\s|$)',
		report,
		re.DOTALL | re.IGNORECASE,
	)
	if key_findings_match:
		section_text = key_findings_match.group(1).strip()
		for line in section_text.split('\n'):
			line = line.strip()
			if not line:
				continue
			line = re.sub(r'^\d+\.\s*', '', line)
			line = re.sub(r'^[-*•]\s*', '', line)
			# Only create issues for lines that indicate failures
			lower = line.lower()
			if any(kw in lower for kw in ['404', 'missing', 'broken', 'error', 'fail', 'not implemented', 'not found', 'bug']):
				# Skip if already referenced by issue number
				if re.search(r'#\d+', line):
					continue
				findings.append(QAFinding(
					title=_truncate(line, 120),
					body=line,
					status='FINDING',
					section='KEY FINDINGS',
				))

	# Deduplicate by normalized title
	seen: set[str] = set()
	unique: list[QAFinding] = []
	for f in findings:
		key = _normalize_title(f.title)
		if key not in seen:
			seen.add(key)
			unique.append(f)

	return unique


def _truncate(s: str, max_len: int) -> str:
	"""Truncate string to max_len, stripping markdown bold markers."""
	s = s.replace('**', '').strip()
	if len(s) > max_len:
		return s[:max_len - 3] + '...'
	return s


def _normalize_title(title: str) -> str:
	"""Normalize a title for deduplication comparison."""
	return re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()


def get_existing_issue_titles(repo: str) -> set[str]:
	"""Fetch existing open issue titles from the repo for dedup."""
	result = subprocess.run(
		['gh', 'issue', 'list', '-R', repo, '--state', 'open', '--limit', '100', '--json', 'title'],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		logger.warning(f'Could not fetch existing issues: {result.stderr}')
		return set()

	issues = json.loads(result.stdout)
	return {_normalize_title(i['title']) for i in issues}


def _ensure_label_exists(repo: str, label: str) -> None:
	"""Create the label if it doesn't exist on the repo."""
	result = subprocess.run(
		['gh', 'label', 'create', label, '-R', repo, '--color', 'D93F0B', '--description', 'Auto-created by browser-use QA'],
		capture_output=True,
		text=True,
	)
	if result.returncode == 0:
		logger.info(f'Created label "{label}" on {repo}')
	# If it already exists, gh returns error — that's fine


def create_issues_from_report(
	report: str,
	repo: str = 'Mark0025/wes',
	dry_run: bool = False,
) -> list[dict[str, str]]:
	"""
	Parse a QA report and create GitHub issues for new findings.

	Args:
		report: The full QA report text (markdown)
		repo: Target GitHub repo (owner/name)
		dry_run: If True, only log what would be created without actually creating

	Returns:
		List of dicts with 'title', 'url', 'status' for each finding processed.
	"""
	findings = parse_report_findings(report)
	if not findings:
		logger.info('No actionable findings found in report.')
		return []

	logger.info(f'Found {len(findings)} actionable findings in report.')

	existing_titles = get_existing_issue_titles(repo)
	logger.info(f'Found {len(existing_titles)} existing open issues on {repo}.')

	if not dry_run:
		_ensure_label_exists(repo, 'browser-use-qa')

	results: list[dict[str, str]] = []
	date_str = datetime.now().strftime('%Y-%m-%d')

	for finding in findings:
		prefixed_title = f'[browser-use QA] {finding.title}'
		normalized = _normalize_title(prefixed_title)

		# Check for duplicates (also check without prefix)
		if normalized in existing_titles or _normalize_title(finding.title) in existing_titles:
			logger.info(f'SKIP (duplicate): {finding.title}')
			results.append({'title': prefixed_title, 'url': '', 'status': 'skipped_duplicate'})
			continue

		# Build issue body
		body_parts = [
			'## QA Finding',
			'',
			f'**Source section**: {finding.section}',
			f'**QA status**: {finding.status}',
			f'**Date tested**: {date_str}',
			'',
			'### Description',
			f'{finding.body}',
		]
		if finding.evidence:
			body_parts.extend(['', '### Evidence', finding.evidence])
		if finding.steps:
			body_parts.extend(['', '### Steps to Reproduce', finding.steps])
		body_parts.extend([
			'',
			'---',
			'*Auto-created by browser-use QA system*',
		])
		body = '\n'.join(body_parts)

		if dry_run:
			logger.info(f'DRY RUN — would create: {prefixed_title}')
			results.append({'title': prefixed_title, 'url': '', 'status': 'dry_run'})
			continue

		# Create the issue
		result = subprocess.run(
			[
				'gh', 'issue', 'create',
				'-R', repo,
				'--title', prefixed_title,
				'--label', 'bug,browser-use-qa',
				'--body', body,
			],
			capture_output=True,
			text=True,
		)

		if result.returncode == 0:
			url = result.stdout.strip()
			logger.success(f'Created issue: {prefixed_title} → {url}')
			results.append({'title': prefixed_title, 'url': url, 'status': 'created'})
			# Add to existing set so we don't create duplicates within the same run
			existing_titles.add(normalized)
		else:
			logger.error(f'Failed to create issue "{prefixed_title}": {result.stderr}')
			results.append({'title': prefixed_title, 'url': '', 'status': f'error: {result.stderr.strip()}'})

	created_count = sum(1 for r in results if r['status'] == 'created')
	skipped_count = sum(1 for r in results if r['status'] == 'skipped_duplicate')
	logger.info(f'Summary: {created_count} created, {skipped_count} skipped (duplicate), {len(results) - created_count - skipped_count} other')

	return results


def main():
	"""CLI entry point: parse a report file and create issues."""
	import argparse
	import sys

	parser = argparse.ArgumentParser(description='Auto-create GitHub issues from QA report findings')
	parser.add_argument('report_file', help='Path to the QA report markdown file')
	parser.add_argument('--repo', default='Mark0025/wes', help='Target GitHub repo (default: Mark0025/wes)')
	parser.add_argument('--dry-run', action='store_true', help='Preview what would be created without actually creating')
	args = parser.parse_args()

	# Configure logging
	logger.remove()
	logger.add(sys.stderr, format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>', level='INFO')

	report_path = Path(args.report_file)
	if not report_path.exists():
		logger.error(f'Report file not found: {report_path}')
		sys.exit(1)

	report = report_path.read_text()
	results = create_issues_from_report(report, repo=args.repo, dry_run=args.dry_run)

	if not results:
		print('No issues to create.')
	else:
		print(f'\n{"=" * 60}')
		print('ISSUE CREATION SUMMARY')
		print(f'{"=" * 60}')
		for r in results:
			status_icon = '✅' if r['status'] == 'created' else '⏭️' if 'skip' in r['status'] else '🔍' if r['status'] == 'dry_run' else '❌'
			url_str = f' → {r["url"]}' if r['url'] else ''
			print(f'{status_icon} [{r["status"]}] {r["title"]}{url_str}')
		print(f'{"=" * 60}')


if __name__ == '__main__':
	main()
