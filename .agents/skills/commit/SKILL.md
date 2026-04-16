---
name: commit
description: "Stage, review, and commit changes with a clean message. Dynamically selects review agents based on change scope. Invoke with $commit or when user says commit this, commit changes."
---

# Enhanced Commit Workflow

Dynamically determines the right level of review based on what changed, then runs the appropriate agents before committing.

## Phase 1: Detect Context

Read `AGENTS.md` in the repo to understand project stack (language, framework, test commands, lint commands).

## Phase 2: Gather Diff

```bash
git status
git diff HEAD --stat
git diff HEAD
git branch --show-current
git log --oneline -10
```

If no changes detected, tell the user and stop.

## Phase 3: Triage - Determine Review Tier

Look at the diff and decide which tier fits. Use your judgment - don't mechanically count points.

**Key signals:**

| Ask yourself | If yes |
|-------------|--------|
| Is this a small, focused change? (1-3 files, under ~50 lines, single concern) | Tier 1 |
| Is this a feature or refactor touching multiple files? (4-8 files, new components, API wiring) | Tier 2 |
| Is this a large change spanning modules? (9+ files, 300+ lines, shared infrastructure, or multi-feature) | Tier 3 |

**Automatic escalation:**
- Committing directly to `main` or `staging` -> minimum Tier 2
- Diff > 2000 lines -> Tier 3, and suggest splitting the commit
- `.env` files or files with "secret"/"key"/"token" in the name -> minimum Tier 1

**User overrides:**
- `--quick` -> force Tier 1
- `--full` -> force Tier 3

**Tell the user the tier before launching agents:**
```
Review tier: STANDARD (4 files, ~180 lines, new component + API wiring)
Launching: Code Quality + Gap Review
```

### Tier 1: QUICK
**1 agent:** Code Quality (thorough single pass since it's the only check)

### Tier 2: STANDARD
**2 agents in parallel:** Code Quality + Gap Review

### Tier 3: FULL
**3 agents in parallel:** Code Quality + Gap Review + Branch Collision

## Phase 4: Branch Data Gathering (Tier 3 only)

Only if Tier 3. Check if a remote exists first (`git remote -v`). If no remote, skip the collision agent entirely and run only 2 agents.

```bash
git fetch --all --quiet 2>/dev/null
git for-each-ref --sort=-committerdate --format='%(refname:short) %(committerdate:relative) %(subject)' refs/remotes/origin/ | head -30

# For each changed file, check cross-branch activity
for f in <each changed file>; do
  echo "=== $f ==="
  git log --all --oneline --since="30 days ago" -- "$f" | head -10
done

gh pr list --state open --limit 20 2>/dev/null || echo "gh CLI not available"
git rev-list --left-right --count origin/staging...HEAD 2>/dev/null || echo "Could not compare"
```

Keep this output - you will paste it directly into Agent 3's prompt.

## Phase 5: Launch Agents

Send ALL agent calls in a **SINGLE message** for parallel execution. For each agent, read its prompt template from the corresponding `.md` file in the `references/` directory of this skill, inject the diff/context data into the placeholders, and use the result as the agent's prompt.

### Agent 1: Code Quality & Security Review (All Tiers)

- Read `references/code-quality-agent.md`
- Inject the full diff into `{DIFF}`

### Agent 2: Gap & Completeness Review (Tier 2+)

- Read `references/gap-review-agent.md`
- Inject the diff into `{DIFF}`, changed file list into `{FILES_CHANGED}`, and any available task context (STATUS.md, conversation history) into `{TASK_CONTEXT}`. If no context available, write "No explicit task context available - infer from the diff."

### Agent 3: Branch Collision & Overlap Review (Tier 3 only)

- Read `references/branch-collision-agent.md`
- Inject the branch name, changed file list, and all branch/PR data gathered in Phase 4 into the template

**Wait for all launched agents to complete.**

## Phase 6: Present Findings

Aggregate results into a single report. Only include sections for agents that ran:

```
PRE-COMMIT REVIEW (Tier N)
===========================

Code Quality (N issues):                    [All Tiers]
  CRITICAL: ...
  HIGH: ...
  MEDIUM: ...

Completeness (N gaps):                      [Tier 2+]
  MISSING: ...
  INCOMPLETE: ...

Branch Collisions (N risks):                [Tier 3 only]
  CONFLICT: ...
  DUPLICATE: ...
  PR AWARENESS: ...

Verdict: PASS / ISSUES FOUND / BLOCKED / COORDINATE FIRST
```

## Phase 7: User Decision

Present the findings and ask the user to choose:
- **Proceed** - commit as-is (acknowledge issues as tech debt)
- **Fix Issues** - stop, user will fix and re-run $commit
- **Cancel** - abort entirely

If user says "Fix Issues" or "Cancel": stop immediately.

## Phase 8: Stage & Commit

Only if user approves:

1. **Identify files to stage.** Exclude:
   - `.env*` files (except `.env.example`)
   - `node_modules/`, `__pycache__/`, `.venv/`
   - Any file that looks like it contains secrets

2. **Stage specific files** (never `git add -A` or `git add .`):
```bash
git add <file1> <file2> ...
```

3. **Write commit message:**
   - If user provided a message, use that
   - Otherwise, generate a clean message: `type: description`
   - Types: `feat`, `fix`, `refactor`, `style`, `docs`, `test`, `chore`
   - Keep under 72 chars, imperative mood
   - NO co-authored-by lines, NO emoji

4. **Commit:**
```bash
git commit -m "type(scope): description"
```

5. **Verify:**
```bash
git log --oneline -3
git status
```

## Edge Cases

- **Lint/tsc commands available** (from AGENTS.md) -> run them BEFORE agents. If they fail hard, report and stop.
- **Unstaged + staged changes mixed** -> show both, ask user which to include.
- **gh CLI not available** -> collision agent works with branch data only, skips PR info.
