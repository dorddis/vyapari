---
name: review-extensive
description: "Deep 6-agent parallel code review covering build, conflicts, gaps, logic, quality, and security. Invoke with $review-extensive for thorough pre-merge review. Use /review for quick reviews."
---

## When to Use

- Before merging to main/staging
- Large PRs (10+ files, 500+ lines)
- Changes touching auth, payments, data models, or shared infrastructure
- When you want maximum confidence before shipping

For quick reviews, use Codex's built-in `/review` instead.

## Phase 1: Gather Data

```bash
git status
git diff HEAD --stat
git diff HEAD
git branch --show-current
git log --oneline -10
```

If reviewing a PR branch against main:
```bash
git diff main...HEAD
git diff main...HEAD --stat
git log main..HEAD --oneline
```

Also gather branch context:
```bash
git fetch --all --quiet 2>/dev/null
git for-each-ref --sort=-committerdate --format='%(refname:short) %(committerdate:relative) %(subject)' refs/remotes/origin/ | head -20

for f in <each changed file>; do
  echo "=== $f ==="
  git log --all --oneline --since="30 days ago" -- "$f" | head -10
done

gh pr list --state open --limit 20 2>/dev/null || echo "gh not available"
```

## Phase 2: Launch 6 Review Agents in Parallel

Spawn ALL 6 agents simultaneously. Each gets the full diff and relevant context. Each focuses on ONE dimension only.

Tell the user:
```
Launching 6-agent extensive review...
  1. Build & Lint Verification
  2. Conflict & Integration
  3. Gap & Completeness
  4. Logic & Correctness
  5. Quality & Maintainability
  6. Security
```

Read each agent's prompt template from `references/` and inject the diff/context.

### Agent 1: Build & Lint Verification
- Read `references/build-agent.md`
- Inject: `{DIFF}`, `{FILES_CHANGED}`

### Agent 2: Conflict & Integration Review
- Read `references/conflict-agent.md` (same prompt as commit skill's branch-collision-agent)
- Inject: `{CURRENT_BRANCH}`, `{FILES_CHANGED}`, `{BRANCH_INFO}`, `{DIFF}`

### Agent 3: Gap & Completeness Review
- Read `references/gap-agent.md` (same prompt as commit skill's gap-review-agent)
- Inject: `{DIFF}`, `{FILES_CHANGED}`, `{TASK_CONTEXT}`

### Agent 4: Logic & Correctness Review
- Read `references/logic-agent.md`
- Inject: `{DIFF}`

### Agent 5: Quality & Maintainability Review
- Read `references/quality-agent.md` (expanded from commit skill's code-quality-agent, minus security - that's agent 6)
- Inject: `{DIFF}`

### Agent 6: Security Review
- Read `references/security-agent.md`
- Inject: `{DIFF}`

**Wait for all 6 agents to complete.**

## Phase 3: Aggregate Results

Compile into a single report:

```
EXTENSIVE CODE REVIEW (6 agents)
==================================

1. Build & Lint:      [PASS/ISSUES/BROKEN]     (N issues)
2. Conflicts:         [CLEAR/RISKS/COORDINATE]  (N risks)
3. Completeness:      [COMPLETE/GAPS/MAJOR]     (N gaps)
4. Logic:             [PASS/BUGS/CRITICAL]      (N bugs)
5. Quality:           [PASS/IMPROVE/REFACTOR]   (N items)
6. Security:          [SECURE/VULNS/CRITICAL]   (N vulns)

CRITICAL issues (must fix):
  - [list all CRITICAL from every agent]

HIGH issues (should fix):
  - [list all HIGH from every agent]

MEDIUM issues (consider):
  - [list all MEDIUM, grouped by agent]

OVERALL VERDICT: SHIP IT / FIX FIRST / BLOCKED
```

## Phase 4: Recommend

Based on the aggregate:
- **SHIP IT** - No critical/high issues across all 6 dimensions
- **FIX FIRST** - Has high issues but nothing critical. List exactly what to fix.
- **BLOCKED** - Has critical issues. Do not merge until resolved.
