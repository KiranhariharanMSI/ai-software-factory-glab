# Holdout scenarios

<!--
  THE BUILDER CANNOT READ THIS FILE.
-->

## A fresh init, backend switched, then a repeat init changes nothing

1. On a throwaway repo, run `factory init --yes` with `backend: github` configured.
2. Count the labels created: exactly **19** (`factory:accepted`, `factory:in-progress`,
   `factory:needs-review`, `factory:validating`, `factory:needs-fix`,
   `factory:approved`, `factory:held`, `factory:merged`, `factory:done`,
   `factory:needs-human`, `factory:rejected`, `factory:deferred`,
   `factory:rate-limited`, `factory:stop`, `factory:from-regression` -- 15 -- plus
   `priority:critical`, `priority:high`, `priority:medium`, `priority:low` -- 4).
3. Switch the config to `backend: local`, with no other change, and run
   `factory doctor`.
4. `factory doctor` reports `origin remote` and `gh authenticated` checks as
   **not applicable / skipped**, never as `[ FAIL ]` -- a backend with no remote
   concept cannot fail a check that assumes one exists.
5. Run `factory init --yes` again, against the original `backend: github` config.
6. The label count is still exactly 19 -- not 38, not 0. Re-running `init` against
   a host that already has the vocabulary must not duplicate it and must not error
   on the duplicate.

**What would make this fail:** a 20th or 18th label after step 2 (an off-by-one in
the vocabulary list itself), a `[ FAIL ]` instead of skip in step 4 for a
network-shaped check under a backend that has no network, or a doubled/errored
label set after the repeat init in step 6.

## Same target, two backends, same resulting state-machine position

1. Using the local backend, create an issue whose title is exactly
   `holdout-probe-7719`, and label it `factory:accepted`.
2. Run `factory run implement gh:issue:1` (or the local backend's equivalent target
   for that issue) against it.
3. Record the exact label the issue carries afterward, and the exact number of
   label-history entries logged for it (append-only, so this only grows): **1**
   transition (`factory:accepted` -> whatever `implement` moves it to), and **0**
   comments beyond whatever the implement workflow itself writes as its plan/PR
   link.
4. Repeat steps 1-2 against the GitHub backend, same title, same starting label, on
   the disposable fork.
5. The resulting label on the GitHub issue is the **same label name** as step 3
   produced locally, and the transition count is still exactly **1** -- the backend
   changed, the state machine's arithmetic did not.

**What would make this fail:** the two backends land the issue in different-looking
states for the identical starting condition and the identical workflow, or either
backend records more than one transition for a single `implement` run that did not
itself fail and retry.
