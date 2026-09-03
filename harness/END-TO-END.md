# End-to-end journeys

<!--
  An agent reads this every validation run, drives the CLI, and reports what it saw.
-->

## How to write one

Each journey is a `##` heading and a numbered list of steps. Write them the way
you would tell a person on a call. The agent decides how to invoke and check.

---

## A maintainer runs one issue through the factory by hand

1. Open a GitHub issue in this repo and label it `factory:accepted`.
2. Run `factory run implement gh:issue:<n>` from the repo root.
3. A new branch appears, and a draft pull request is opened referencing the issue
   (`Fixes #<n>` in its body).
4. The issue's label has moved from `factory:accepted` to `factory:in-progress` or
   `factory:needs-review` -- never back to `factory:accepted`, and never absent.

**What would make this fail:** no branch or PR appears, the PR body does not
reference the issue, or the label is unchanged after the run completes.

## A maintainer checks the factory's own health

1. Run `python factory/doctor.py` from the repo root.
2. The output lists each check as `[ ok ]`, `[ warn ]`, or `[ FAIL ]`, one per line.
3. Each `[ FAIL ]` line names the specific autonomy level it blocks (e.g.
   "blocks level 2+").
4. The last line reads `HIGHEST EARNED AUTONOMY LEVEL: <N>   (configured: <M>)`,
   with `N` no higher than the lowest level any `[ FAIL ]` blocks.

**What would make this fail:** a failing check with no blocked-level annotation, or
a highest-earned level that is higher than a `[ FAIL ]` line says it should be.

## A maintainer raises the dial and is refused without evidence

1. With at least one gate-relevant check still `[ FAIL ]` (mutation set, ratchet
   floor, or holdout still scaffolded), run `factory level 3`.
2. The command refuses, and names which `factory doctor` failure is blocking it.
3. The dial (`factory status`) still reads its previous value, unchanged.

**What would make this fail:** the dial moves to 3 anyway, or the refusal does not
say why.
