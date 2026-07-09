---
name: issue
description: Implement a GitHub issue end-to-end — branch, code, test, docs, and commit.
argument-hint: "<issue-number>"
allowed-tools: Agent Bash(git *) Bash(gh *) Bash(cd *) Bash(make *) Bash(npm *) Bash(uv *) Bash(python *) Bash(cat *) Bash(ls *) Bash(mkdir *) Bash(cp *) Read Edit Write Grep Glob TaskCreate TaskUpdate TaskGet TaskList
---

# Issue Implementation

Implement a GitHub issue end-to-end: fetch the issue, create a feature branch, implement all requirements, test, update docs, and commit.

## Input

`$ARGUMENTS` must be a GitHub issue number (e.g. `78`). If missing or non-numeric, ask the user for the issue number.

## Step 1: Fetch the Issue

Run `gh issue view $ARGUMENTS --json title,body,labels` to get the issue details.

Also check if a matching markdown file exists under `tmp/issues/` by looking for files that start with a zero-padded version of the issue number (e.g. issue 78 maps to a file starting with `078-`). If the file exists, read it for additional context.

Display the issue title and a brief summary to the user.

## Step 2: Create Feature Branch

Determine the branch name from the matching issue markdown filename under `tmp/issues/`, but without the `.md` extension. For example, if the file is `078-my-feature.md`, the branch name is `078-my-feature`.

If no matching file exists, derive the branch name from the issue number and title: zero-pad the issue number to 3 digits, kebab-case the title, and join with a hyphen (e.g. `078-my-feature-title`).

Create and switch to the feature branch: `git checkout -b <branch-name>`.

## Step 3: Plan the Implementation

Read the full issue body and any linked markdown file. Identify all discrete requirements.

Create a task list using TaskCreate for each requirement so progress can be tracked.

Before writing any code, present the implementation plan to the user and wait for confirmation.

## Step 4: Implement

Use an agent team to parallelize independent work where possible:

- **Backend changes**: Implement in `backend/` following project conventions (Python, FastAPI, type hints, SQLAlchemy).
- **Frontend changes**: Implement in `frontend/` following project conventions (TypeScript, ESM, shadcn, Tailwind, Vite).
- **Infrastructure changes**: Implement in `iac/` following AWS SAM / CloudFormation conventions.
- **Agent changes**: Implement in `agents/` with isolated virtual environments.

Update TaskUpdate as each requirement is completed.

## Step 5: Test

Run existing tests to check for regressions:

- Backend: `cd backend && make test` (or the appropriate makefile target)
- Frontend: `cd frontend && npm test` (if test scripts exist)
- Agent tests: Run tests within each modified agent directory.

If the issue specifies new test cases, implement and run them.

All tests must pass before proceeding.

## Step 6: Update Documentation

Update the following documentation files to reflect the new changes:

- **SPECIFICATIONS.md**: Update any relevant specification files with the latest design decisions. Search for SPECIFICATIONS.md files in all subdirectories.
- **README.md**: Update any relevant README files with the latest implementation details. Ensure no sensitive or account-specific information is included (no ARNs, account IDs, tokens, or endpoint URLs).

## Step 7: Final Validation

Run the full test suite one more time to confirm nothing was broken during documentation updates.

Review all changes with `git diff` to verify correctness and ensure no secrets or credentials are included.

## Step 8: Commit

Stage and commit all changes locally using semantic commit messages. Group related changes into logical commits:

- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation updates
- `test:` for test additions
- `refactor:` for code restructuring
- `chore:` for build/config changes

Do NOT push to remote. Only commit locally.

Append `Co-Authored-By: Claude <noreply@anthropic.com>` to each commit message.

Report a summary of all commits created.
