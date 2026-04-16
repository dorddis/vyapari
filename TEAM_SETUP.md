# Codex CLI - Team Setup Guide

Quick setup for the Low Cortisol Gang. Get Codex running in 5 minutes.

## 1. Install Codex CLI

```bash
npm install -g @openai/codex
```

Requires Node.js 18+. Verify: `codex --version` (should show 0.120.0+).

## 2. Authenticate

```bash
codex
```

This opens a browser for ChatGPT sign-in. Use your personal OpenAI account (Plus/Pro recommended for GPT-5 access). If the hackathon provides API credits:

```bash
export CODEX_API_KEY=sk-your-key-here
```

## 3. Clone & Trust the Project

```bash
git clone https://github.com/dorddis/ai-sales-agent.git
cd ai-sales-agent/vyapari
codex  # First run in a new project asks to trust it - say yes
```

## 4. Recommended Config

Create/edit `~/.codex/config.toml`:

```toml
model = "gpt-5.4"
model_reasoning_effort = "high"
personality = "pragmatic"
approval_policy = "never"
sandbox_mode = "danger-full-access"

[agents]
max_threads = 6
max_depth = 1

[features]
multi_agent = true
shell_tool = true
fast_mode = true

[history]
persistence = "save-all"
```

## 5. Hackathon Profile (Speed Mode)

Add this to your `~/.codex/config.toml`:

```toml
[profiles.hackathon]
model = "gpt-5.4"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "danger-full-access"
web_search = "live"
```

Then run with: `codex --profile hackathon`

## 6. Aliases (Optional)

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
alias cx='codex --full-auto'
alias cxh='codex --profile hackathon'
alias cxy='codex --dangerously-bypass-approvals-and-sandbox'
alias cxe='codex exec'
alias cxr='codex resume --last'
```

## 7. What's Already Set Up

The repo includes:

| File | What it does |
|------|-------------|
| `AGENTS.md` | Project instructions. Codex reads this automatically every session. |
| `.agents/skills/commit/` | Smart commit workflow with tiered review (quick/standard/full) |
| `.agents/skills/wrap/` | Session wrap-up (STATUS.md update, session logs, git commit) |
| `.agents/skills/review-extensive/` | 6-agent parallel code review (build, conflicts, gaps, logic, quality, security) |

## 8. Using Skills

```
# Inside Codex session:
$commit              # Smart commit with review
$commit --quick      # Quick commit, minimal review
$commit --full       # Full review with branch collision check
$wrap session-name   # Wrap up session
$review-extensive    # Deep 6-agent review
/review              # Codex's built-in quick review
```

## 9. Key Commands

| Command | What |
|---------|------|
| `/status` | Show model, tokens, config |
| `/fast` | Toggle fast mode |
| `/compact` | Compress context (saves tokens) |
| `/diff` | Show git diff |
| `/review` | Quick built-in review |
| `/plan` | Plan before implementing |
| `/agent` | Switch between agent threads |
| `/fork` | Branch conversation |
| `!command` | Run shell command inline |
| `@filepath` | Reference a file |

## 10. Workflow Tips

- **Start sessions with:** `codex --profile hackathon` or `cxh` alias
- **Reference files:** `@src/agents/sales_agent.py` in your prompt
- **Parallel work:** Codex can spawn up to 6 subagents simultaneously
- **Resume later:** `codex resume --last` picks up where you left off
- **One-shot tasks:** `codex exec "add error handling to src/api/routes.py"`
- **Web search:** Add `--search` flag for live web lookups during session

## 11. Git Conventions

- Conventional commits: `type(scope): description`
- Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`
- No co-authored-by lines
- Stage specific files, never `git add -A`
- No `.env` files in commits
