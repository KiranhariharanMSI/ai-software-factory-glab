# Mission

<!--
  Owner: humans only. This file is on the protected list; the factory cannot edit it.
-->

**Derived from:** conversation with the repo owner, 2026-09-03 (no separate PRD)
**Last reconciled with it:** 2026-09-03

## What ai-software-factory-glab is

A fork of `ai-software-factory` -- a CLI (`factory.py`, plus the Archon workflow
engine) that turns a repository into a "dark factory": a GitHub issue is checked
against a mission, planned, built, judged by something that did not write it, and
merged, with no human reading the diff. This fork's specific job is to make that
mechanism work against **GitLab-backed repos**, not only GitHub, by replacing the
hard-coded `gh` calls with a pluggable state backend (`local` / `gitlab` / `github`).

Single-repo assumption: one installed factory governs exactly one repository. That
does not change here -- this fork adds a second target VCS, not multi-repo
orchestration.

## Who it is for

- A maintainer who wants the factory's issue-to-merge loop to run against a
  GitLab-hosted repository (self-hosted or gitlab.com), where today it only speaks
  GitHub.

ai-software-factory-glab is not a general git-hosting abstraction layer, and not a
new product on top of the factory -- it is the same factory, made to work on a
second host.

## Core capabilities (in scope)

The factory may accept issues in these areas.

**Backend abstraction**
- A single interface covering every VCS operation the runtime needs: view/list
  issues and PRs, add/remove labels, close/reopen, comment, create a label,
  create/merge a PR, view a repo.
- A config value (`backend: local | gitlab | github`) that selects the
  implementation at runtime, with no other code change required to switch.

**GitLab backend**
- A working implementation of that interface against the GitLab REST API (directly
  or via `glab`), with correct semantics: right subcommands, right flags, right
  JSON field names, right MR-number extraction from GitLab URLs, right merge
  behaviour (immediate merge, not queued auto-merge-on-pipeline).

**Local backend**
- A working implementation backed by local markdown/JSON files under `.factory/`,
  for testing the dispatcher/gate/watchdog mechanics with no network and no VCS
  account at all.

**GitHub backend**
- The existing, already-working `gh`-based implementation, refactored behind the
  same interface without changing its behaviour.

## Out of scope -- the factory must never build this

<!--
  NEVER, NOT "NOT YET".
-->

**Surface area**
- A GUI or web dashboard for the factory. It stays a CLI, permanently.
- Support for VCS platforms beyond local/GitHub/GitLab (no Bitbucket, no Gitea, no
  Azure DevOps, no custom ticket tracker).

**Scope creep on this specific change**
- Any change to the merge-safety core -- the ratchet, the watchdog, the protected
  files list, the verdict-file merge mechanism -- as part of adding a backend.
  Those are correct today; this work must not touch them.
- Multi-repo or cross-repo orchestration. One factory instance still governs
  exactly one repository, one mission, one holdout, regardless of backend.
- New autonomy levels, or any change to what a given dial position means.

**Operational**
- Telemetry, analytics, or usage collection added anywhere in the runtime.
- Publishing this fork as a package to PyPI, npm, or any other registry.

## Hard invariants -- not tunable by any issue

1. **Exactly one backend is active per installed factory.** An issue may add a
   backend or fix one; it may not make the runtime talk to two backends in the same
   repo at once. Ambiguity here is exactly the kind of thing the state machine
   cannot recover from mid-tick.
2. **The interface, not the call sites, is the contract.** `state.py`, `merge.py`,
   `open-pr.py` and the triage scripts call the backend interface. No script may
   shell out to `gh`/`glab` directly once the interface exists -- that reintroduces
   the exact coupling this fork exists to remove.
3. **The factory cannot modify governance files.** `MISSION.md`, `FACTORY_RULES.md`
   and the conventions file are the constitution. A PR touching any of them is an
   automatic reject.
4. **The factory cannot modify its own judge.** `harness/`, `.factory/locks/` and
   `.factory/holdout/` define what "working" means here. Adding an assertion is
   always welcome; removing or loosening one is a human decision, always.

## Allowed evolutions

Explicitly in scope, so the factory does not reject them as architectural drift:

- Adding a new backend implementation behind the existing interface (e.g. a fourth
  VCS) is a welcome extension, not drift, once the interface itself is stable.
- Improving error messages, retry behaviour, and field-mapping accuracy inside an
  existing backend is free to improve without limit.

## Definition of done

Every change the factory ships clears all three gates.

**Gate 1 -- static checks and tests pass.** `python -m compileall -q .` and
`python factory/_selftest.py`.

**Gate 2 -- switching `backend` in config is the only change needed to change VCS.**
No code edit, no re-`init`, required to move a repo from one backend to another.

**Gate 3 -- the end-to-end path passes as a real user.**

1. Run `factory doctor` against the configured backend.
2. Run `factory run implement gh:issue:<n>` (or the backend's equivalent target
   syntax) by hand.
3. Observe the branch, PR/MR, and label transitions the backend produced.
4. They match what the same command would have produced against GitHub, modulo the
   host's own vocabulary (MR vs PR, `opened` vs `OPEN`).

This runs on every change that touches runnable code, including ones that "seem
unrelated". It is not optional.

## Open questions -- decisions nobody has made yet

These are undecided, not forbidden. **The factory may propose an answer to any of
them**, build against it, and record what it assumed -- the merge is then held for a
human, so nothing ships on a guess and nothing stops for one.

- **Q1** Whether the GitLab backend targets the `glab` CLI (thin wrapper, faster to
  ship) or the GitLab REST API directly (no dependency on `glab` being installed,
  more code to own). Default assumption if unanswered: wrap `glab`, because the
  binary already exists and is what was tested against.
- **Q2** Whether `glab mr merge`'s default auto-merge-on-pipeline behaviour should be
  suppressed (`--auto-merge=false`) to match GitHub's immediate-merge semantics, or
  left as GitLab's native default. Default assumption if unanswered: suppress it --
  the factory's merge gate already re-checks state before merging, so an immediate
  merge matches what `merge.py` was written to expect.

**Except these, which do stop the factory** -- they are on the irreversible list
(`FACTORY_RULES.md` §7.3) rather than open in the ordinary sense:

- Which VCS account/token the factory authenticates as (identity/auth-shaped).
- Anything that would delete or rewrite existing issues, labels, or PRs/MRs on the
  target host as part of a migration between backends.

Once answered, an entry moves to `.factory/decisions.md` with its answer and date,
and stops being asked. **A decision is asked once.**

## What the factory does NOT own -- permanently human

- Whether a given backend's error messages are actually *helpful* to a person
  debugging a failed dispatch, versus merely correct.
- Whether the choice of `glab`-wrapper vs raw-REST-API (Q1) is the right call for
  where this fork is actually deployed.
- Whether GitLab's terminology (MR, `opened`/`closed`, `iid`) should ever be
  surfaced back to the user as-is, or normalised to GitHub's vocabulary in logs and
  messages.

The factory owns the backend interface's correctness -- that every call site through
it produces the same observable state-machine transition regardless of which
backend is active. That is the layer whose correctness can be asserted, and it is
reviewed by a human, on purpose, forever, for everything above.
