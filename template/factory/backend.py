"""The one interface every VCS operation goes through. MISSION hard invariant 2.

Flat module functions, no ABC: `resolve(name)` binds each operation in OPERATIONS
onto this module's globals from the implementation named by `config.BACKEND`. The
operations: view_issue, view_pr, list_issues, list_prs, create_issue, close_issue,
reopen_issue, edit_labels, add_label, remove_label, create_label, list_labels,
comment, comment_texts, create_pr, ready_pr, merge_pr, repo_view.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


class BackendError(RuntimeError):
    pass


OPERATIONS = (
    "view_issue", "view_pr", "list_issues", "list_prs", "create_issue",
    "close_issue", "reopen_issue", "edit_labels", "add_label", "remove_label",
    "create_label", "list_labels", "comment", "comment_texts", "create_pr",
    "ready_pr", "merge_pr", "repo_view",
)

_IMPLS = {"github": "backend_github", "local": "backend_local"}


def resolve(name: str):
    if name not in _IMPLS:
        raise BackendError(
            f"unknown backend {name!r}; valid values: {sorted(_IMPLS)}. A gitlab "
            f"backend is a separate issue."
        )
    import importlib

    return importlib.import_module(_IMPLS[name])


_impl = resolve(config.BACKEND)
ACTIVE = config.BACKEND
for _name in OPERATIONS:
    if not hasattr(_impl, _name):
        raise BackendError(f"{_impl.__name__} does not implement {_name}")
    globals()[_name] = getattr(_impl, _name)
