"""The `glab` CLI implementation of backend.py's contract. No `raw()` escape
hatch -- that is the point, same as `backend_github.py`.

A `gh` -> `glab` rename fails on most of the commands this factory issues: the
field names differ (`iid` vs `number`), the enum values differ (`opened` vs
`OPEN`), labels come back as bare strings instead of `{"name": ...}` objects,
and `glab` has no `--json` field-selection flag at all. So this module
translates VOCABULARY, not just command names -- every normaliser below
*constructs* a GitHub-shaped dict rather than patching GitLab's, so a stray
GitLab field can never reach a caller that only knows GitHub's shape.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from backend import BackendError  # noqa: E402

# Reused, not re-derived: these signatures are HTTP- and network-level, not
# host-level, so a second copy is a copy that goes stale, and the stale one is
# the one that pages somebody at 3am. Importing this executes no `gh` call --
# that module only defines constants and functions at import time.
from backend_github import _TRANSIENT, _is_transient  # noqa: E402


def _glab(*args: str, check: bool = True, stdin: str | None = None,
          attempts: int = 3, timeout: int = 120) -> str:
    last = None
    for attempt in range(1, attempts + 1):
        p = subprocess.run(
            ["glab", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=stdin,
            cwd=str(config.ROOT),
            timeout=timeout,
        )
        if p.returncode == 0 or not check:
            return p.stdout
        last = p
        if attempt == attempts or not _is_transient(p.stderr or ""):
            break
        # Retrying an answer just asks the same question three times before
        # reporting the same thing -- this only fires for the narrow,
        # network-level list in _TRANSIENT.
        print(
            f"GLAB_RETRY {attempt}/{attempts - 1} after a transient failure: "
            f"{(p.stderr or '').strip()[:160]}",
            file=sys.stderr, flush=True,
        )
        time.sleep(2 * attempt)
    raise BackendError(
        f"glab {' '.join(args)} failed ({last.returncode}): {(last.stderr or '').strip()}"
    )


def _json(out):
    try:
        return json.loads(out or "[]")
    except json.JSONDecodeError as e:
        raise BackendError(f"unparseable response from glab: {e}") from e


_STATE = {"opened": "OPEN", "closed": "CLOSED", "merged": "MERGED"}
_LIST_STATE = {"open": "opened", "closed": "closed", "merged": "merged", "all": "all"}


def _state(raw) -> str:
    # An unrecognised GitLab state must NEVER fall through to "OPEN": merge.py
    # merges on `state == "OPEN"`, so an unmapped value has to read as anything
    # else. Fail toward refusing the merge.
    return _STATE.get(raw, (raw or "").upper())


# GitLab's merge_status / detailed_merge_status -> the PAIR merge.py reads.
#
# ONE GITLAB VALUE ANSWERS TWO DIFFERENT QUESTIONS, and merge.py says so out
# loud: `mergeable` is "is there a conflict", `mergeStateStatus` is "will the
# host actually let this through". A protected base branch is MERGEABLE and
# BLOCKED AT THE SAME TIME -- that pair is precisely what branch protection
# looks like. Collapsing them into one value makes the branch-protection
# diagnosis unreachable: the mergeable check fires first and a human gets
# "mergeable=CONFLICTING" for a branch with no conflict, re-runs, and gets the
# same useless answer forever.
_MERGE_STATE = {
    "can_be_merged":            ("MERGEABLE",   "CLEAN"),
    "mergeable":                ("MERGEABLE",   "CLEAN"),
    "conflict":                 ("CONFLICTING", "DIRTY"),
    "cannot_be_merged":         ("CONFLICTING", "DIRTY"),
    "blocked_status":           ("MERGEABLE",   "BLOCKED"),
    "ci_still_running":         ("MERGEABLE",   "BLOCKED"),
    "discussions_not_resolved": ("MERGEABLE",   "BLOCKED"),
    "not_approved":             ("MERGEABLE",   "BLOCKED"),
    "need_rebase":              ("MERGEABLE",   "BLOCKED"),
    "unchecked":                ("UNKNOWN",     "UNKNOWN"),
    "checking":                 ("UNKNOWN",     "UNKNOWN"),
    "cannot_be_merged_recheck": ("UNKNOWN",     "UNKNOWN"),
}


def _merge_state(raw: dict) -> tuple[str, str]:
    key = raw.get("detailed_merge_status") or raw.get("merge_status")
    # Anything unmapped becomes UNKNOWN/UNKNOWN, which merge.py already
    # refuses on -- fail toward refusing the merge, never toward merging one.
    return _MERGE_STATE.get(key, ("UNKNOWN", "UNKNOWN"))


def _labels(raw) -> list[dict]:
    out = []
    for n in raw or []:
        out.append({"name": n["name"] if isinstance(n, dict) else n})
    return out


def _issue(raw: dict) -> dict:
    # Constructed, never `dict(raw)` + patch: `-F json` returns the whole
    # object, and a passthrough would put GitLab's `description`, `notes`,
    # `merge_commit_message` in front of the validator.
    return {
        "number": int(raw["iid"]),
        "title": raw.get("title"),
        "body": raw.get("description") or "",
        "labels": _labels(raw.get("labels")),
        "state": _state(raw.get("state")),
        "url": raw.get("web_url") or "",
        "author": {"login": (raw.get("author") or {}).get("username", "")},
        "createdAt": raw.get("created_at") or "",
    }


def _mr(raw: dict) -> dict:
    item = _issue(raw)
    mergeable, merge_state_status = _merge_state(raw)
    try:
        changed = int(raw["changes_count"])
    except (KeyError, TypeError, ValueError):
        changed = None
    item.update({
        "headRefName": raw.get("source_branch"),
        "baseRefName": raw.get("target_branch"),
        "isDraft": bool(raw.get("draft", raw.get("work_in_progress", False))),
        "mergeable": mergeable,
        "mergeStateStatus": merge_state_status,
        "changedFiles": changed,
        "additions": None,
        "deletions": None,
    })
    return item


def view_issue(num):
    return _issue(_json(_glab("issue", "view", num, "-F", "json")))


def view_pr(num):
    return _mr(_json(_glab("mr", "view", num, "-F", "json")))


def list_issues(state="open", limit=100, label=None):
    args = ["issue", "list", "--state", _LIST_STATE[state], "--per-page",
            str(limit), "-F", "json"]
    if label:
        args += ["--label", label]
    return [_issue(i) for i in _json(_glab(*args))]


def list_prs(state="open", limit=100, head=None):
    args = ["mr", "list", "--state", _LIST_STATE[state], "--per-page",
            str(limit), "-F", "json"]
    if head:
        args += ["--source-branch", head]
    return [_mr(m) for m in _json(_glab(*args))]


def create_issue(title, body, labels):
    args = ["issue", "create", "--title", title, "--description", body, "--yes"]
    for lbl in labels:
        args += ["--label", lbl]
    out = _glab(*args)
    return (out or "").strip().splitlines()[-1] if out else ""


def close_issue(num, reason):
    # glab has no --reason (dropped, not faked) and no --yes on `issue close`.
    _glab("issue", "close", num, check=False)


def reopen_issue(num):
    # `issue reopen` has no --yes either.
    _glab("issue", "reopen", num, check=False)


def edit_labels(kind, num, add=(), remove=(), check=True):
    # `issue update` has no --yes flag; `mr update` does (and needs it to skip
    # a confirmation prompt). Verified against `glab <verb> update --help` for
    # each -- the two commands' flag surfaces genuinely differ here.
    verb = "issue" if kind == "issue" else "mr"
    args = [verb, "update", num]
    for lbl in add:
        args += ["--label", lbl]
    for lbl in remove:
        args += ["--unlabel", lbl]
    if verb == "mr":
        args += ["--yes"]
    if add or remove:
        _glab(*args, check=check)


def add_label(kind, num, *labels, check=True):
    edit_labels(kind, num, add=labels, check=check)


def remove_label(kind, num, *labels, check=True):
    edit_labels(kind, num, remove=labels, check=check)


def create_label(name, colour, description):
    # The `#` matters -- callers pass bare hex, GitLab wants it prefixed.
    # `label create` has no --yes flag at all (verified against --help); it
    # was here as a copy-paste from another verb and made every call fail
    # with "Unknown flag: --yes", silently swallowed by check=False.
    hexed = colour if colour.startswith("#") else f"#{colour}"
    _glab("label", "create", "--name", name, "--color", hexed,
          "--description", description, check=False)


def list_labels():
    return [lbl["name"] for lbl in _json(_glab("label", "list", "--per-page",
                                                "300", "-F", "json"))]


def comment(kind, num, body):
    # glab has no --body-file -; the body goes through argv as one string, one
    # process, keeping state.py's "posted in one call" guarantee.
    #
    # `issue note <id> --message` posts directly and has no --yes flag.
    # `mr note` is a command GROUP on this glab version -- there is no bare
    # `mr note <id> --message`, it needs the `create` subcommand, and that
    # subcommand has no --yes either. The two verbs are not parallel here.
    if kind == "issue":
        _glab("issue", "note", num, "--message", body)
    else:
        _glab("mr", "note", "create", num, "--message", body)


def comment_texts(kind, num):
    verb = "issue" if kind == "issue" else "mr"
    return _glab(verb, "view", num, "--comments", check=False)


def create_pr(base, head, title, body_path, draft=True):
    try:
        description = Path(body_path).read_text(encoding="utf-8")
    except OSError as e:
        raise BackendError(f"could not read PR body file {body_path}: {e}") from e
    args = ["mr", "create", "--source-branch", head, "--target-branch", base,
            "--title", title, "--description", description, "--yes"]
    if draft:
        args.append("--draft")
    out = _glab(*args, check=False, timeout=300)
    url = (out or "").strip().splitlines()[-1] if out else ""
    return url or None


def ready_pr(num):
    _glab("mr", "update", num, "--ready", "--yes", check=False)


def merge_pr(num, subject, body):
    p = subprocess.run(
        ["glab", "mr", "merge", num, "--squash", "--message", subject + "\n\n" + body,
         "--auto-merge=false", "--yes"],
        cwd=str(config.ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    return p.returncode, p.stderr.strip()


def repo_view():
    raw = _json(_glab("api", "projects/:id"))
    namespace = raw.get("namespace") or {}
    owner = namespace.get("full_path") or (raw.get("path_with_namespace") or "").split("/")[0]
    if not owner:
        raise BackendError("glab api projects/:id returned no namespace or path_with_namespace")
    return {"owner": {"login": owner}}
