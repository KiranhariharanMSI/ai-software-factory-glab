# PRD: pluggable VCS backend for ai-software-factory

**Status:** draft, backing `MISSION.md`
**Author:** repo owner, compressed into `MISSION.md` by the setup agent
**Date:** 2026-09-03

## Problem

`ai-software-factory` is hard-wired to GitHub. Every place the runtime needs to
read or change repository state -- issues, labels, comments, PRs -- shells out to
the `gh` CLI directly, with GitHub-specific flags and GitHub-shaped JSON fields
baked into `state.py`, `merge.py`, `open-pr.py`, and the triage scripts (roughly 21
distinct call shapes, catalogued against this fork's source).

That blocks anyone whose repos live on GitLab (self-hosted or gitlab.com) from
using the factory at all -- not as a matter of configuration, but because the
mechanism the whole state machine runs on (label-driven issue/PR transitions)
assumes GitHub's vocabulary and semantics throughout. A naive `gh`-to-`glab`
command-renaming shim was tested against the real commands the factory issues and
fails on the majority of them: missing subcommands (`glab` has no `issue edit`),
missing flags (`glab mr merge` has no `--subject`/`--body`), incompatible JSON
shapes (`--json <fields>` vs `-F json` dumping everything), and incompatible URL
formats (GitLab MRs are `/-/merge_requests/N`, not `/pull/N`, breaking the regex
that extracts a PR number after creation).

## Goals

1. Make the factory's core loop -- issue read, label transition, comment, PR/MR
   open, PR/MR merge -- work correctly against GitLab, with the same observable
   state-machine behavior it already has against GitHub.
2. Do it without a second copy of `state.py`/`merge.py`/`open-pr.py`: one set of
   call sites, one interface, backend-specific code isolated behind it.
3. Make a fully offline, no-network backend available (`local`), so the
   dispatcher/gate/watchdog mechanics can be tested and demonstrated without any
   VCS account at all.
4. Preserve today's GitHub behavior exactly. This is additive, not a rewrite of the
   thing that already works.

## Non-goals

- A general git-hosting abstraction library usable outside this factory.
- Support for any VCS beyond local / GitHub / GitLab (see `MISSION.md`
  out-of-scope: no Bitbucket, Gitea, Azure DevOps).
- Any change to the merge-safety core: the ratchet, the watchdog, the protected
  files list, the verdict-file merge mechanism. Those are correct today.
- Multi-repo orchestration. One installed factory still governs exactly one
  repository, on exactly one backend, at a time.
- A GUI. The factory stays a CLI.

## Users

A maintainer who has already run `factory init` against a repo and wants the
dispatcher, gate, and merge loop to work whether that repo lives on GitHub or
GitLab -- and, for testing the factory itself, without any real VCS at all.

## Requirements

### R1 -- Backend interface

A single interface every call site uses instead of shelling out to `gh` directly:
`view_issue`, `list_issues`, `add_label` / `remove_label`, `close_issue`,
`reopen_issue`, `comment`, `create_label`, `list_labels`, `create_pr`, `merge_pr`,
`repo_view`. Scope is exactly the operations the runtime uses today -- not a
speculative superset.

### R2 -- GitHub backend (parity, not new work)

The existing `gh`-based logic, moved behind the interface. Byte-for-byte the same
observable behavior as before this change.

### R3 -- GitLab backend

A correct implementation against GitLab's actual API/CLI surface:
- Label add/remove via `issue update --label/--unlabel` (GitLab has no `issue
  edit`).
- JSON field mapping GitHub's flat `--json <fields>` selection onto GitLab's
  full-object `-F json` output, translating field names and enum values
  (`opened`/`closed` vs `OPEN`/`CLOSED`, `iid` vs `number`) at the boundary so
  call sites never see the difference.
- PR/MR number extraction that matches GitLab's URL shape
  (`/-/merge_requests/N`), not GitHub's.
- Merge behavior that matches GitHub's immediate-merge semantics rather than
  `glab mr merge`'s default auto-merge-on-pipeline queuing, since `merge.py`'s gate
  already re-verifies state right before merging and was written assuming the
  merge happens now.

### R4 -- Local backend

A file-backed implementation under `.factory/` (issues and PRs as files with
frontmatter for state/labels, comments appended to the file, "merge" as a local
`git merge`) -- no network, no account, no token.

### R5 -- Config surface

One config key, `backend: local | gitlab | github`, read by `factory/config.py`.
Switching it is the only change required to change which backend is active; no
code edit, no re-`init`.

## Success criteria

- Running the same `factory run implement gh:issue:<n>` against the same starting
  issue state produces the same resulting label/PR state regardless of which
  backend is configured (this is asserted directly in
  `.factory/holdout/HOLDOUT.md`'s second scenario).
- `factory doctor`'s `gh authenticated` / `origin remote` checks degrade to
  not-applicable/skipped under the local backend rather than reporting `[ FAIL ]`
  for a network concept that backend doesn't have.
- `factory/_selftest.py` continues to pass in full, plus new invariants asserting
  no script outside the backend module shells out to `gh`/`glab` directly.

## Rollout

Scoped into separate issues rather than one PR, to stay inside `FACTORY_RULES.md`'s
per-PR caps (500 production lines / 12 files / 1500 total):

1. **Issue #1 (filed):** interface + GitHub backend behind it, no behavior change.
2. Local backend, once the interface exists and issue #1 has proven it out.
3. GitLab backend, same interface, real network validation against a disposable
   GitLab project before any production repo.

## Open questions

Carried into `MISSION.md` verbatim so the factory may propose and record an
answer rather than stopping for one:

- Q1: `glab`-CLI wrapper vs raw GitLab REST API for the GitLab backend.
- Q2: whether to suppress `glab mr merge`'s auto-merge-on-pipeline default.
