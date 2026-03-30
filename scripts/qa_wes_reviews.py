"""
AI QA Tester for wes (Fair Deal House Buyer) - Reviews Page

Uses browser-use + ChatClaudeCode to visually inspect the reviews page,
check known GitHub issues, and report what works vs what's broken.

Usage:
    cd ~/browser-use
    uv run python scripts/qa_wes_reviews.py
"""

import asyncio
import json
import subprocess

from browser_use import Agent
from browser_use.llm.claude_code.chat import ChatClaudeCode


def get_github_issues() -> str:
	"""Pull open issues from Mark0025/wes."""
	result = subprocess.run(
		['gh', 'issue', 'list', '-R', 'Mark0025/wes', '--state', 'open', '--limit', '20', '--json', 'number,title,labels,body'],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		return 'Failed to fetch issues'

	issues = json.loads(result.stdout)
	lines = []
	for issue in issues:
		labels = ', '.join(l['name'] for l in issue.get('labels', []))
		lines.append(f"- #{issue['number']}: {issue['title']} [{labels}]")
	return '\n'.join(lines)


async def main():
	issues = get_github_issues()
	print(f'Fetched {len(issues.splitlines())} open issues from Mark0025/wes\n')

	# Using Claude Code SDK — subscription-based, $0 API cost
	llm = ChatClaudeCode(model='sonnet', timeout=120.0)

	task = f"""You are a QA tester inspecting the Fair Deal House Buyer website.

## Your Mission
1. Go to https://dev.fairdealhousebuyer.com/reviews
2. Thoroughly inspect the page visually and interactively
3. Check all these aspects:
   - Does the page load correctly?
   - Are reviews/testimonials displayed?
   - Is the layout responsive and professional?
   - Do any images load or are they broken?
   - Are there any visible errors, console errors, or broken UI elements?
   - Do any buttons/links work when clicked?
   - Is the navigation working (header, footer links)?
   - Does the page look like a real business site or does it look unfinished?

4. Then navigate to these pages too and check them:
   - https://dev.fairdealhousebuyer.com/ (homepage)
   - https://dev.fairdealhousebuyer.com/about
   - https://dev.fairdealhousebuyer.com/how-it-works

5. Cross-reference what you see with these known open GitHub issues:
{issues}

## Output Format
At the end, provide a structured QA report with:

### WORKING (things that look good)
- List each thing that works correctly

### BROKEN (things that are broken or look wrong)
- List each broken thing with a description
- Reference the GitHub issue number if it matches a known issue

### NEW ISSUES (things broken that are NOT in the issue list)
- List any new problems you found that aren't tracked yet

### OVERALL SCORE
- Give a score out of 10 for production readiness
- One paragraph summary of the site's current state
"""

	agent = Agent(
		task=task,
		llm=llm,
		use_vision=True,
		max_actions_per_step=3,
		llm_timeout=180,
		step_timeout=240,
	)

	result = await agent.run(max_steps=20)

	# Print the final result
	print('\n' + '=' * 80)
	print('QA REPORT')
	print('=' * 80)
	if result and result.history:
		for entry in result.history:
			if hasattr(entry, 'result') and entry.result:
				for r in entry.result:
					if hasattr(r, 'extracted_content') and r.extracted_content:
						print(r.extracted_content)
	print('=' * 80)


if __name__ == '__main__':
	asyncio.run(main())
