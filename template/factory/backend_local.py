"""A file-backed implementation of backend.py's contract. No network, no account,
no `gh` -- issues, PRs and the label registry live as files under `config.LOCAL_DIR`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from backend import BackendError  # noqa: E402


def _store() -> Path:
    root = Path(config.LOCAL_DIR)
    (root / "issues").mkdir(parents=True, exist_ok=True)
    (root / "prs").mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise BackendError("malformed local record: missing frontmatter fence")
    meta: dict = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        i += 1
    body = "\n".join(lines[i + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def _render(meta: dict, body: str) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(body)
    return "\n".join(lines) + "\n"


def _path(kind: str, num) -> Path:
    folder = "issues" if kind == "issue" else "prs"
    return _store() / folder / f"{num}.md"


def _write(kind: str, num, meta: dict, body: str) -> None:
    path = _path(kind, num)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(_render(meta, body), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise BackendError(f"could not write local {kind} #{num}: {e}") from e


def _read_raw(kind: str, num) -> tuple[dict, str]:
    path = _path(kind, num)
    if not path.exists():
        raise BackendError(f"no local {kind} #{num} at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise BackendError(f"could not read local {kind} #{num}: {e}") from e
    return _parse(text)


def _read(kind: str, num) -> dict:
    meta, body = _read_raw(kind, num)
    labels = [n.strip() for n in meta.get("labels", "").split(",") if n.strip()]
    item = dict(meta)
    try:
        item["number"] = int(meta["number"])
    except (KeyError, ValueError) as e:
        raise BackendError(f"malformed local {kind} #{num}: bad number field ({e})") from e
    item["body"] = body
    item["labels"] = [{"name": n} for n in labels]
    item["author"] = {"login": meta.get("author", "local")}
    item["isDraft"] = meta.get("isDraft", "false").strip().lower() == "true"
    return item


def _labels_file() -> Path:
    return _store() / "labels.json"


def _load_labels() -> list[dict]:
    path = _labels_file()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BackendError(f"could not read {path}: {e}") from e


def _save_labels(labels: list[dict]) -> None:
    try:
        _labels_file().write_text(json.dumps(labels), encoding="utf-8")
    except OSError as e:
        raise BackendError(f"could not write {_labels_file()}: {e}") from e


def _counter_file() -> Path:
    return _store() / "counter.json"


def _next_number() -> int:
    path = _counter_file()
    try:
        n = json.loads(path.read_text(encoding="utf-8"))["next"] if path.exists() else 1
    except (OSError, json.JSONDecodeError, KeyError) as e:
        raise BackendError(f"could not read {path}: {e}") from e
    try:
        path.write_text(json.dumps({"next": n + 1}), encoding="utf-8")
    except OSError as e:
        raise BackendError(f"could not write {path}: {e}") from e
    return n


def view_issue(num):
    return _read("issue", num)


def view_pr(num):
    return _read("pr", num)


def _list(kind: str, state: str, limit: int, label, head_filter=None) -> list[dict]:
    folder = "issues" if kind == "issue" else "prs"
    items = []
    for path in sorted((_store() / folder).glob("*.md"), key=lambda p: int(p.stem)):
        item = _read(kind, int(path.stem))
        if state != "all" and item["state"] != state.upper():
            continue
        if label and label not in [lbl["name"] for lbl in item["labels"]]:
            continue
        if head_filter and item.get("headRefName") != head_filter:
            continue
        items.append(item)
    return items[:limit]


def list_issues(state="open", limit=100, label=None):
    return _list("issue", state, limit, label)


def list_prs(state="open", limit=100, head=None):
    return _list("pr", state, limit, None, head_filter=head)


def create_issue(title, body, labels):
    known = {lbl["name"] for lbl in _load_labels()}
    unknown = [lbl for lbl in labels if lbl not in known]
    if unknown:
        raise BackendError(f"unknown label(s) on create_issue: {unknown}")
    num = _next_number()
    meta = {
        "number": num,
        "title": title,
        "state": "OPEN",
        "labels": ", ".join(labels),
        "url": f"local:issue:{num}",
        "author": "local",
        "createdAt": _now(),
    }
    _write("issue", num, meta, body)
    return f"local:issue:{num}"


def close_issue(num, reason):
    try:
        meta, body = _read_raw("issue", num)
    except BackendError:
        return
    meta["state"] = "CLOSED"
    meta["closedReason"] = reason
    _write("issue", num, meta, body)


def reopen_issue(num):
    try:
        meta, body = _read_raw("issue", num)
    except BackendError:
        return
    meta["state"] = "OPEN"
    _write("issue", num, meta, body)


def edit_labels(kind, num, add=(), remove=(), check=True):
    try:
        meta, body = _read_raw(kind, num)
    except BackendError:
        if check:
            raise
        return
    current = [n.strip() for n in meta.get("labels", "").split(",") if n.strip()]
    if add:
        known = {lbl["name"] for lbl in _load_labels()}
        unknown = [lbl for lbl in add if lbl not in known]
        if unknown and check:
            raise BackendError(f"unknown label(s): {unknown}")
        for lbl in add:
            if lbl not in current:
                current.append(lbl)
    for lbl in remove:
        if lbl in current:
            current.remove(lbl)
    meta["labels"] = ", ".join(current)
    _write(kind, num, meta, body)


def add_label(kind, num, *labels, check=True):
    edit_labels(kind, num, add=labels, check=check)


def remove_label(kind, num, *labels, check=True):
    edit_labels(kind, num, remove=labels, check=check)


def create_label(name, colour, description):
    labels = _load_labels()
    for lbl in labels:
        if lbl["name"] == name:
            lbl["color"] = colour
            lbl["description"] = description
            _save_labels(labels)
            return
    labels.append({"name": name, "color": colour, "description": description})
    _save_labels(labels)


def list_labels():
    return [lbl["name"] for lbl in _load_labels()]


def comment(kind, num, body):
    meta, existing = _read_raw(kind, num)
    existing += f"\n\n## comment {_now()}\n\n{body}\n"
    _write(kind, num, meta, existing)


def comment_texts(kind, num):
    _, body = _read_raw(kind, num)
    return body


def create_pr(base, head, title, body_path, draft=True):
    try:
        body = Path(body_path).read_text(encoding="utf-8")
    except OSError as e:
        raise BackendError(f"could not read PR body file {body_path}: {e}") from e
    num = _next_number()
    meta = {
        "number": num,
        "title": title,
        "state": "OPEN",
        "labels": "",
        "url": f"local:pr:{num}",
        "author": "local",
        "createdAt": _now(),
        "headRefName": head,
        "baseRefName": base,
        "isDraft": "true" if draft else "false",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }
    _write("pr", num, meta, body)
    return f"local:pr:{num}"


def ready_pr(num):
    try:
        meta, body = _read_raw("pr", num)
    except BackendError:
        return
    meta["isDraft"] = "false"
    _write("pr", num, meta, body)


def merge_pr(num, subject, body):
    view = _read("pr", num)  # BackendError if the PR does not exist
    head, base = view["headRefName"], view["baseRefName"]
    # A local `git merge` here is filesystem plumbing, not a VCS-account escape
    # hatch: no push, no remote, no `gh`. MISSION invariant 2 forbids reaching
    # PAST the backend interface for account state; this call sits inside it.
    p = subprocess.run(
        ["git", "merge", "--no-ff", "-m", subject + "\n\n" + body, head],
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    if p.returncode == 0:
        meta, mbody = _read_raw("pr", num)
        meta["state"] = "CLOSED"
        meta["merged"] = "true"
        _write("pr", num, meta, mbody)
    return p.returncode, (p.stderr or "").strip()


def repo_view():
    return {"owner": {"login": "local"}}
