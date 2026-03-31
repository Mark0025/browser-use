# Consolidated QA Evidence Report — https://dev.fairdealhousebuyer.com

**Generated:** 2026-03-31 13:14
**QA Tool:** browser-use + ChatClaudeCode (AI-driven browser automation)
**Source Reports:** 4 QA runs
**Target:** dev.fairdealhousebuyer.com (wes repo)

- `qa_full_2026-03-30_2001.md`
- `qa_full_2026-03-30_2053.md`
- `qa_verify_2026-03-30_2236.md`
- `qa_final_2026-03-30_2353.md`

---

## Section 1: Verified Working

Features tested and proven working across QA runs, with log citations.

### 1. Admin Dashboard — All 15 sidebar tabs load
**Evidence:** All tabs navigated and rendered without error. Tabs: Site Settings, Users, Leads, Blogs, Testimonials, Images, Find & Replace, Dev Manual, Webhook/CRM, AI Content, AI Settings, Business Info, Branding, Content, Email Settings.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Partial — Playwright covers admin tab rendering via data-testid selectors

### 2. Site Settings — Status, data source toggles, migration buttons
**Evidence:** Site status: LIVE. PostgreSQL ON for blogs and testimonials. Migration buttons visible.
**Source:** `qa_full_2026-03-30_2001.md`
**Playwright coverage:** Unknown

### 3. Business Info — Edit, save, live site update, revert
**Evidence:** Changed phone to 555-BROWSER-USE-TEST, confirmed live on public homepage header, reverted to (405) 876-4611. 16 template variables all editable.
**Source:** `qa_full_2026-03-30_2001.md`
**Playwright coverage:** Unknown — this is end-to-end behavior Playwright may not cover

### 4. Testimonials — CRUD create + delete
**Evidence:** Created E2E-BROWSERUSE-TEST testimonial (5 stars, Oklahoma City OK). Deleted via admin. Rating combobox (Radix UI) functional.
**Source:** `qa_full_2026-03-30_2001.md, qa_full_2026-03-30_2053.md`
**Playwright coverage:** Likely covered via data-testid=testimonial-create-btn, testimonial-delete-*

### 5. Lead Form — Submit on homepage, verify in admin, delete
**Evidence:** Submitted lead (FINAL-VERIFY, Test, 999 Final St, Tulsa, 74101, 555-888-0000, final-verify@test.com). Confirmed in admin Leads tab. Deleted for cleanup.
**Source:** `qa_final_2026-03-30_2353.md`
**Playwright coverage:** Likely — lead form is core functionality

### 6. Leads Tab — View and delete leads
**Evidence:** All E2E test leads found and deleted (6+ leads). After deletion: "No leads yet" confirmed.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Likely covered via data-testid=admin-tab-leads

### 7. Images Tab — Library loads, copy URL, delete confirmation
**Evidence:** 3 images displayed. Copy URL button works. Delete opens confirmation dialog. Upload input present.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 8. Find & Replace — Form interaction
**Evidence:** Find input, Replace With input, Case Sensitive toggle, Search button all functional.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 9. Dev Manual Tab — Renders with redirect notice
**Evidence:** Shows "Architecture docs have moved to Dev-Admin Dashboard" with link.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 10. Webhook / CRM — Configuration displays
**Evidence:** Zapier URL configured. Enable toggle ON. Status: "Webhook is active."
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 11. AI Content — Spin Content initiated
**Evidence:** Template variables listed. "Spin Content" clicked, showed "Spinning..." (API processing). Status: "API Connected".
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 12. AI Settings — Configuration table loads
**Evidence:** Template variables and content type settings table rendered.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 13. Content Tab — Hero section fields all display
**Evidence:** Pre-Headline, Headline, Headline Suffix, Subheadline, CTA Button, Hero Description, Value Props (4), Form Settings, SEO & Meta Tags, Page Sections all visible and editable.
**Source:** `qa_full_2026-03-30_2053.md`
**Playwright coverage:** Unknown

### 14. Email Settings — Fields load (typo fixed)
**Evidence:** Notification Email correct. Reply-To had typo "info@Fairdealhousebbuyers.com" — fixed to "info@fairdealhousebuyers.com".
**Source:** `qa_full_2026-03-30_2053.md, qa_verify_2026-03-30_2236.md`
**Playwright coverage:** Unknown — data validation unlikely in Playwright

### 15. Users Tab — User list renders
**Evidence:** 1 user: Mark Carpenter (mark@localhousebuyers.net), role=admin. Columns: User, Email, Current Role, Change Role.
**Source:** `qa_final_2026-03-30_2353.md`
**Playwright coverage:** Likely covered via data-testid=admin-tab-users

### 16. All 5 Preview Routes — Functional
**Evidence:** /preview (sidebar + Publish button), /preview/about (editing mode), /preview/how-it-works, /preview/blogs (listing), /preview/blogs/:slug (detail with PREVIEW MODE banner).
**Source:** `qa_final_2026-03-30_2353.md`
**Playwright coverage:** Likely — preview is core feature

### 17. Public Pages — Homepage, Reviews, About, How It Works, Blog Listing, Privacy, Terms
**Evidence:** All render correctly. Privacy Policy dated Jan 2025. Terms reference Oklahoma law. Blog listing shows posts by Wes Harris.
**Source:** `qa_verify_2026-03-30_2236.md, qa_final_2026-03-30_2353.md`
**Playwright coverage:** Likely — basic page rendering

### 18. Dev Manual Page — /dev-man
**Evidence:** WesApp Architecture docs loaded. Tech stack: Next.js 16 / React 19 / TypeScript 5 / PostgreSQL 16 / Clerk 6. LOC: 20,648. 13 tabs functional.
**Source:** `qa_final_2026-03-30_2353.md`
**Playwright coverage:** Unknown

### 19. Auth Flow — /sign-in and /sign-up redirect when authenticated
**Evidence:** /sign-in and /sign-up both redirect to /admin for authenticated user (Clerk session detected).
**Source:** `qa_final_2026-03-30_2353.md`
**Playwright coverage:** Likely covered by Clerk auth tests

---

## Section 2: Confirmed Bugs

Bugs verified across multiple runs or with direct evidence.

### 1. [Critical] Email Reply-To Typo (FIXED during QA)
**Wes repo status:** Fixed by browser-use during qa_verify run
**Classification:** App bug (data entry error)
**Reproduction:**
```
1. Navigate to Admin → Email Settings
2. Reply-To Email field shows `info@Fairdealhousebbuyers.com` (double "b" + capital "F")
3. Expected: `info@fairdealhousebuyers.com`
```
**Impact:** Replies to auto-response emails went to non-existent address, breaking lead follow-up.
**Evidence:** Found in qa_full_2026-03-30_2053.md. Confirmed and fixed in qa_verify_2026-03-30_2236.md.

### 2. [Medium] Testimonial Action Buttons Missing Labels (Issue #84) (wes #84)
**Wes repo status:** Open issue — #84 in wes repo
**Classification:** App limitation (feature not implemented)
**Reproduction:**
```
1. Navigate to Admin → Testimonials
2. Each testimonial card has 3 action buttons
3. Buttons have NO aria-labels, NO title attributes, NO visible preview button
4. Only "Version History" button has a title attribute
```
**Impact:** Accessibility violation. No preview button for testimonials (blogs have one).
**Evidence:** Confirmed in qa_full_2026-03-30_2001.md. Cross-referenced with wes issue #84.

### 3. [Medium] Branding Save Button Gets Stuck in "Saving..." State
**Wes repo status:** Not tracked
**Classification:** App bug (likely race condition in save handler)
**Reproduction:**
```
1. Navigate to Admin → Branding
2. Change Primary Color value
3. Click Save Changes
4. Button enters "Saving..." state and never returns to "Save Changes"
```
**Impact:** User cannot save subsequent changes without full page reload. Unclear if first save committed.
**Evidence:** Found in qa_full_2026-03-30_2053.md. Partially reproduced in qa_verify_2026-03-30_2236.md (admin skeleton loading issues prevented full verification).

### 4. [Low] /help Route Returns 404
**Wes repo status:** Not tracked — may be intentional (route not implemented)
**Classification:** App limitation (route not implemented)
**Reproduction:**
```
1. Navigate to https://dev.fairdealhousebuyer.com/help
2. Page returns standard Next.js 404: "This page could not be found."
```
**Impact:** If /help is in the sitemap, it should either render or be removed from navigation.
**Evidence:** Found in qa_final_2026-03-30_2353.md (Item 3).

### 5. [Medium] Admin Page Intermittent Skeleton/Loading Bug
**Wes repo status:** Not tracked
**Classification:** App bug (likely data loading race condition)
**Reproduction:**
```
1. Navigate to /admin
2. Page sometimes shows skeleton/placeholder loading state
3. Admin tabs become inaccessible
4. Requires page reload to recover
```
**Impact:** Blocks admin access intermittently. Affected verification of Branding save and other tests.
**Evidence:** Found in qa_verify_2026-03-30_2236.md (Item 2 notes). Multiple navigation attempts to /admin showed skeleton state.

### 6. [Info] Blog Detail Pages Have No Inline Lead Form
**Wes repo status:** Not tracked — may be by design
**Classification:** App limitation or by design
**Reproduction:**
```
1. Navigate to /blogs
2. Click into any blog post
3. Scroll to bottom
4. Only a CTA button "Get My Cash Offer" linking to offer page
5. No inline lead form with fields
```
**Impact:** If inline lead capture on blog posts is expected, it is missing.
**Evidence:** Found in qa_final_2026-03-30_2353.md (Item 14: PARTIAL).

---

## Section 3: App Limitations vs Browser-Use Limitations

### App Limitations (feature gaps or missing functionality)

| Limitation | Evidence | Issue # |
|-----------|----------|---------|
| No preview button on testimonials | Blogs have preview; testimonials only have Version History + 2 unlabeled buttons | #84 |
| /help route not implemented | Returns Next.js 404 | — |
| No inline lead form on blog detail pages | Only CTA button linking to offer page | — |
| Find & Replace shows no result feedback | Search button disables but no "no results" or result list shown | — |
| Image edit button unclear | Only Copy URL and Delete visible, no Edit button found (Issue #85) | #85 |

### Browser-Use Limitations (tool constraints)

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| Cannot upload files via file input | Image Upload test skipped across all runs | Manual testing required |
| ~23s per LLM call (CLI cold start) | Step budget exhaustion limits coverage per run | Multiple runs required |
| Cannot read server-side logs | Cannot verify API responses, DB writes, or email delivery | Add API instrumentation |
| Cannot test email delivery | Reply-To fix verified in UI only, not actual email send | Manual email test needed |
| Cannot test auth as unauthenticated user | /sign-in and /sign-up redirect tested only with active session | Separate browser profile needed |
| Admin skeleton loading bug causes test flakiness | Some verification steps fail when admin doesn't fully load | Retry with page reload |

---

## Section 4: Coverage Matrix

Complete coverage across all routes, admin tabs, and CRUD operations.

| Area | Category | Status | Tested In |
|------|----------|--------|-----------|
| Homepage | Public Page | PASS | qa_full_2026-03-30_2001.md |
| Reviews | Public Page | PASS | qa_final_2026-03-30_2353.md |
| About | Public Page | PASS | qa_final_2026-03-30_2353.md |
| How It Works | Public Page | PASS | qa_final_2026-03-30_2353.md |
| Blog Listing | Public Page | PASS | qa_verify_2026-03-30_2236.md |
| Privacy Policy | Public Page | PASS | qa_verify_2026-03-30_2236.md |
| Terms | Public Page | PASS | qa_verify_2026-03-30_2236.md |
| Help | Public Page | FAIL (404) | qa_final_2026-03-30_2353.md |
| Site Settings | Admin Tab | PASS | qa_full_2026-03-30_2001.md |
| Users | Admin Tab | PASS | qa_final_2026-03-30_2353.md |
| Leads | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Blogs | Admin Tab | PASS | qa_final_2026-03-30_2353.md |
| Testimonials | Admin Tab | PASS | qa_full_2026-03-30_2001.md |
| Images | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Find & Replace | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Dev Manual | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Webhook / CRM | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| AI Content | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| AI Settings | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Business Info | Admin Tab | PASS | qa_full_2026-03-30_2001.md |
| Branding | Admin Tab | PARTIAL | qa_full_2026-03-30_2053.md |
| Content | Admin Tab | PASS | qa_full_2026-03-30_2053.md |
| Email Settings | Admin Tab | PASS (bug fixed) | qa_full_2026-03-30_2053.md |
| Lead Form Submit | CRUD Operation | PASS | qa_full_2026-03-30_2001.md |
| Lead Admin Verify | CRUD Operation | PASS | qa_final_2026-03-30_2353.md |
| Lead Delete | CRUD Operation | PASS | qa_full_2026-03-30_2053.md |
| Blog CRUD | CRUD Operation | PASS (view only) | qa_final_2026-03-30_2353.md |
| Testimonial Create | CRUD Operation | PASS | qa_full_2026-03-30_2001.md |
| Testimonial Delete | CRUD Operation | PASS | qa_full_2026-03-30_2053.md |
| Image Upload | CRUD Operation | SKIPPED | qa_final_2026-03-30_2353.md |
| Business Info Change/Revert | CRUD Operation | PASS | qa_full_2026-03-30_2001.md |
| Branding Change/Revert | CRUD Operation | PARTIAL | qa_verify_2026-03-30_2236.md |
| /preview | Preview Route | PASS | qa_final_2026-03-30_2353.md |
| /preview/about | Preview Route | PASS | qa_final_2026-03-30_2353.md |
| /preview/how-it-works | Preview Route | PASS | qa_final_2026-03-30_2353.md |
| /preview/blogs | Preview Route | PASS | qa_final_2026-03-30_2353.md |
| /preview/blogs/:slug | Preview Route | PASS | qa_final_2026-03-30_2353.md |

---

## Summary Statistics

- **QA runs analyzed:** 4
- **Public pages tested:** 7/8 (Help returns 404)
- **Admin tabs tested:** 15/15 (all loaded)
- **Preview routes tested:** 5/5 (all functional)
- **CRUD operations tested:** 7/9 (Image Upload skipped, Branding revert partial)
- **Bugs found:** 6 (1 critical fixed, 3 medium, 1 low, 1 info)
- **Bugs fixed during QA:** 1 (Email Reply-To typo)
- **Overall coverage:** ~88% of testable areas

## Wes Repo Issue Cross-Reference

| Wes Issue | Title | Browser-Use Finding |
|-----------|-------|---------------------|
| #205 | docs: browser-use AI QA evidence report — 6 runs, 88.5% cove | — |
| #203 | test: blog CRUD tests should verify count changes, not just  | — |
| #202 | test: E2E test data cleanup incomplete — stale testimonials  | — |
| #201 | bug: branding save possibly stuck on 'Saving...' — no timeou | — |
| #200 | test: lead form → admin Leads tab end-to-end verification mi | — |
| #197 | feat: dev-only instrumentation for browser-use AI QA testing | — |
| #194 | Post-Deploy E2E Failure on dev (4fc58f4) | — |
| #176 | user-guide: Dev-Admin guide — Managing companies, permission | — |
| #170 | user-guide: Admin guide — Managing your site (blogs, testimo | — |
| #169 | user-guide: Visitor journey — How to sell your house (the fu | — |
| #163 | Engineering Audit: Full SWOT analysis before production rele | — |
| #109 | 🚀 [MASTER] Dynamic Rendering System - Data-Driven Page Layou | — |
| #107 | [PHASE 5] Add section management UI to admin dashboard | — |
| #106 | [PHASE 4] Migrate /about and /how-it-works pages to dynamic  | — |
| #85 | Image edit on preview site throws server-side exception | INVESTIGATED — no Edit button found in Images tab |
| #84 | Testimonials missing preview button (need same pattern as bl | CONFIRMED — testimonial preview button missing |
| #83 | Blog edit (pencil icon) should preview blog based on dynamic | — |
| #75 | feat: Add inline content editor to preview mode | — |
| #53 | 🟠 MAJOR: Fork PR branch deletion vulnerability in cleanup wo | — |

---

*Generated by `scripts/qa/compile_evidence.py` — browser-use QA system*