# CLAUDE.md

## Project overview

Automated US stock trading opportunity scanner analyzing stocks with market cap >= $2B daily using multiple trading strategies. Generates web-based reports with AI-powered analysis. Read the README.md for project details when needed.

## Working Orchestration

### 1. Plan Node Default

- Enter Plan moe for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop

- After ANY correction from the user: update TradeScanner/.claude/reference/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons untilmistake rate dropsReview lessons at session start for relevant project

### 4. Verification Before Done

- Never mark a task comp lete without proving it worksDiff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance

- (Balanced)For non-trivial changes: pause and ask "is there amore elegant way?"
- If afix feels hacky: "Knowing everything I know now, imp lement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer- Challenge your own work before presenting it

### 6. Autonomous Bug Fizing

- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests
- then resolve them- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to docs/todo.md' with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to tasks/todo.md
6. **Capture Lessons**: Update lessons.md after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior deve loper standards.
- \*_Minimat Impact_: Changes should only touch what's necessary. Avoid introducing bugs.

## Coding guideline

Read the rules and agent definitions in .claude/ before starting work.

### 1. General

- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.

### 2. Output

- Return code first. Explanation after, only if non-obvious.
- No inline prose. Use comments sparingly - only where logic is unclear.
- No boilerplate unless explicitly requested.

### 3. Code Rules

- Simplest working solution. No over-engineering.
- No abstractions for single-use operations.
- No speculative features or "you might also want..."
- Read the file before modifying it. Never edit blind.
- No docstrings or type annotations on code not being changed.
- No error handling for scenarios that cannot happen.
- Three similar lines is better than a premature abstraction.

### 4. Review Rules

- State the bug. Show the fix. Stop.
- No suggestions beyond the scope of the review.
- No compliments on the code before or after the review.

### 5. Debugging Rules

- Never speculate about a bug without reading the relevant code first.
- State what you found, where, and the fix. One pass.
- If cause is unclear: say so. Do not guess.

### 6. Simple Formatting

- No em-dashes, smart quotes, or decorative Unicode symbols.
- Plain hyphens and straight quotes only.
- Natural language characters (accented letters, CJK, etc.) are fine when the content requires them.
- Code output must be copy-paste safe.
