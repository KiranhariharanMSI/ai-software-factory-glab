"""The `gh` CLI implementation of backend.py's contract. Moved from state.py,
identical in behaviour. No `raw()` escape hatch -- that is the point.
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

# Failures that mean "ask again", not "something is wrong". GitHub returns these
# routinely and they clear in seconds.
#
# THE INCIDENT: a single HTTP 503 on `gh issue list` took down one tick, wrote a
# needs-human entry and sent a notification. The very next tick, sixty seconds
# later, succeeded. So a thirty-second blip in somebody else's service produced a
# page and a permanent record that a human had to clear.
#
# That is the wrong threshold in the expensive direction. This runs unattended for
# days; a channel that fires on every upstream hiccup is a channel people mute, and
# a muted channel is the failure the escalation path exists to prevent.
#
# Deliberately NARROW. A 404, a 422, a bad token or a rejected merge are answers,
# and retrying an answer just asks the same question three times before reporting
# the same thing.
_TRANSIENT = (
    "503", "502", "504", "500",
    "service unavailable", "bad gateway", "gateway time-out", "timeout",
    "connection reset", "connection refused", "could not resolve host",
    "temporarily unavailable", "try again", "eof occurred", "tls handshake",
)

def _is_transient(stderr: str) -> bool:
    low = stderr.lower()
    return any(sig in low for sig in _TRANSIENT)

def _gh(*args: str, check: bool = True, stdin: str | None = None,
        attempts: int = 3, timeout: int = 120) -> str:
    last = None
    for attempt in range(1, attempts + 1):
        p = subprocess.run(
            ["gh", *args],
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
        print(
            f"GH_RETRY {attempt}/{attempts - 1} after a transient failure: "
            f"{(p.stderr or '').strip()[:160]}",
            file=sys.stderr, flush=True,
        )
        time.sleep(2 * attempt)
    raise BackendError(
        f"gh {' '.join(args)} failed ({last.returncode}): {(last.stderr or '').strip()}"
    )

def _json(out):
    try:
        return json.loads(out or "[]")
    except json.JSONDecodeError as e:
        raise BackendError(f"unparseable response from gh: {e}") from e

_ISSUE_FIELDS = "number,title,body,labels,state,url,author,createdAt"
# HOLDOUT: only the fields the validator needs. No comments, no reviews, no commit
# messages -- the coder's chatter must not reach the judge even by accident, and
# excluding it at the fetch layer is what makes that structural rather than a
# sentence in a prompt.
_PR_FIELDS = (
    "number,title,body,labels,state,url,author,headRefName,baseRefName,"
    "additions,deletions,changedFiles,isDraft,mergeable,mergeStateStatus"
)
_ISSUE_LIST_FIELDS = "number,title,labels,state,author,createdAt"
_PR_LIST_FIELDS = "number,title,body,labels,state,url,headRefName,createdAt"

def view_issue(num):
    return _json(_gh("issue", "view", num, "--json", _ISSUE_FIELDS))

def view_pr(num):
    return _json(_gh("pr", "view", num, "--json", _PR_FIELDS))

def list_issues(state="open", limit=100, label=None):
    args = ["issue", "list", "--state", state, "--limit", str(limit),
            "--json", _ISSUE_LIST_FIELDS]
    if label:
        args += ["--label", label]
    return _json(_gh(*args))

def list_prs(state="open", limit=100, head=None):
    args = ["pr", "list", "--state", state, "--limit", str(limit),
            "--json", _PR_LIST_FIELDS]
    if head:
        args += ["--head", head]
    return _json(_gh(*args))

def create_issue(title, body, labels):
    args = ["issue", "create", "--title", title, "--body-file", "-"]
    for lbl in labels:
        args += ["--label", lbl]
    out = _gh(*args, stdin=body)
    return (out or "").strip().splitlines()[-1] if out else ""

def close_issue(num, reason):
    _gh("issue", "close", num, "--reason", reason, check=False)

def reopen_issue(num):
    _gh("issue", "reopen", num, check=False)

def edit_labels(kind, num, add=(), remove=(), check=True):
    verb = "issue" if kind == "issue" else "pr"
    args = ["edit", num]
    for lbl in add:
        args += ["--add-label", lbl]
    for lbl in remove:
        args += ["--remove-label", lbl]
    if add or remove:
        _gh(verb, *args, check=check)

def add_label(kind, num, *labels, check=True):
    edit_labels(kind, num, add=labels, check=check)

def remove_label(kind, num, *labels, check=True):
    edit_labels(kind, num, remove=labels, check=check)

def create_label(name, colour, description):
    _gh("label", "create", name, "--color", colour, "--description", description,
        check=False)

def list_labels():
    return [lbl["name"] for lbl in _json(_gh("label", "list", "--limit", "300",
                                              "--json", "name"))]

def comment(kind, num, body):
    verb = "issue" if kind == "issue" else "pr"
    _gh(verb, "comment", num, "--body-file", "-", stdin=body)

def comment_texts(kind, num):
    verb = "issue" if kind == "issue" else "pr"
    return _gh(verb, "view", num, "--json", "comments", check=False)

def create_pr(base, head, title, body_path, draft=True):
    args = ["pr", "create", "--base", base, "--head", head, "--title", title,
            "--body-file", body_path]
    if draft:
        args.append("--draft")
    out = _gh(*args, check=False, timeout=300)
    url = (out or "").strip().splitlines()[-1] if out else ""
    return url or None

def ready_pr(num):
    _gh("pr", "ready", num, check=False)

def merge_pr(num, subject, body):
    p = subprocess.run(
        ["gh", "pr", "merge", num, "--squash", "--subject", subject, "--body", body],
        cwd=str(config.ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    return p.returncode, p.stderr.strip()

def repo_view():
    return _json(_gh("repo", "view", "--json", "owner"))
