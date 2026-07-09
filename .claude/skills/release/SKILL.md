---
name: release
description: Increment the release version, draft release notes, and prepare a GitHub release.
disable-model-invocation: true
argument-hint: "[new-version]"
allowed-tools: Bash(git *) Bash(gh *) Read Edit Grep Glob
---

# Release Preparation

Prepare a new release for the Loom project.

## Step 1: Read Current Version

Read the current version from both files:
- `backend/pyproject.toml` — the `version` field under `[project]`
- `frontend/package.json` — the `"version"` field

Display the current version to the user.

## Step 2: Determine New Version

If `$ARGUMENTS` is provided and is a valid semantic version (e.g. `1.2.0`), use it as the new version.

Otherwise, ask the user what the new version should be. Suggest the next patch, minor, and major versions based on the current version (e.g. if current is `1.1.0`, suggest `1.1.1`, `1.2.0`, or `2.0.0`).

Wait for the user to confirm before proceeding.

## Step 3: Update Version Files

Update the version in all three files:
- `backend/pyproject.toml`: update the `version = "..."` line
- `frontend/package.json`: update the `"version": "..."` line
- `backend/app/main.py`: update both `version="..."` occurrences (FastAPI app and health endpoint)

## Step 4: Commit Version Changes

Commit the version bumps:
1. Run `git add backend/pyproject.toml frontend/package.json backend/app/main.py`
2. Commit with message `chore: bump version to <new-version>`

## Step 5: Draft Release Notes

Identify the previous release tag by running `git tag --list 'v*' --sort=-version:refname | head -1`.

Generate a changelog from commits since that tag: `git log <previous-tag>..HEAD --oneline`.

Also run `git diff <previous-tag>..HEAD --stat` to summarize scope.

Draft release notes in markdown with:
- A heading `# v<new-version> Release Notes`
- Grouped sections by area (features, fixes, infrastructure, docs, etc.)
- A stats line with files changed and lines added/removed

Present the draft to the user for review before proceeding.

## Step 6: Prepare GitHub Release

After the user approves the release notes:

1. Create a git tag: `git tag v<new-version>`
2. Push the commit and tag: `git push && git push --tags`
3. Create a GitHub release using `gh release create v<new-version> --title "v<new-version>" --notes "<release-notes>"`

Confirm each destructive step (push, tag, release creation) with the user before executing.
