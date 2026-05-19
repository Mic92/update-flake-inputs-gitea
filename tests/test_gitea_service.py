"""Tests for GiteaService merge style handling."""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from update_flake_inputs.gitea_service import GiteaService


@dataclass
class StubGiteaService(GiteaService):
    """GiteaService with controllable API responses."""

    api_url: str = "https://gitea.example.com"
    token: str = "test-token"  # noqa: S105
    owner: str = "test-owner"
    repo: str = "test-repo"

    # Responses to return from _make_request, keyed by (method, endpoint)
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Requests that were made, as (method, endpoint, data) tuples
    requests: list[tuple[str, str, dict[str, object] | None]] = field(
        default_factory=list,
    )

    def __post_init__(self) -> None:  # noqa: D105
        self.api_url = self.api_url.rstrip("/")
        self._validate_token()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, object] | None = None,
    ) -> Any:  # noqa: ANN401
        self.requests.append((method, endpoint, data))
        return self.responses.get((method, endpoint), {})


def _make_service(
    *,
    merge_style: str = "default",
    default_merge_style: str = "rebase",
) -> StubGiteaService:
    responses = {
        ("GET", "/user"): {"login": "testuser"},
        ("GET", "/repos/test-owner/test-repo"): {
            "permissions": {"admin": True},
            "default_merge_style": default_merge_style,
        },
    }
    return StubGiteaService(merge_style=merge_style, responses=responses)


class TestMergeStyleInit:
    def test_default_falls_back_to_merge(self) -> None:
        """When repo response lacks default_merge_style, fall back to merge."""
        responses: dict[tuple[str, str], Any] = {
            ("GET", "/user"): {"login": "testuser"},
            ("GET", "/repos/test-owner/test-repo"): {
                "permissions": {"admin": True},
            },
        }
        svc = StubGiteaService(responses=responses)
        assert svc.merge_style == "merge"

    def test_explicit_merge_style_not_overridden(self) -> None:
        """Test that an explicit merge_style is not replaced by the repo default."""
        svc = _make_service(merge_style="squash", default_merge_style="rebase")
        assert svc.merge_style == "squash"

    def test_empty_string_not_overridden(self) -> None:
        """Test that empty string merge_style is preserved (omit Do from API)."""
        svc = _make_service(merge_style="", default_merge_style="rebase")
        assert svc.merge_style == ""


class TestMergeStyleInRequest:
    def test_merge_style_sent_as_do(self) -> None:
        """Test that merge_style is sent as the Do field in the merge request."""
        svc = _make_service(merge_style="rebase")
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert data["Do"] == "rebase"

    def test_empty_merge_style_omits_do(self) -> None:
        """Test that empty merge_style omits Do from the merge request."""
        svc = _make_service(merge_style="")
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert "Do" not in data

    def test_default_resolves_and_sends_repo_merge_style(self) -> None:
        """Test that 'default' resolves to repo default_merge_style and sends it as Do."""
        svc = _make_service(default_merge_style="squash")
        assert svc.merge_style == "squash"
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert data["Do"] == "squash"


@dataclass
class OfflineGiteaService(GiteaService):
    """GiteaService that skips token validation for offline tests."""

    api_url: str = "https://gitea.example.com"
    token: str = "test-token"  # noqa: S105
    owner: str = "test-owner"
    repo: str = "test-repo"

    def __post_init__(self) -> None:
        """Skip token validation in offline tests."""
        self.api_url = self.api_url.rstrip("/")

    def _validate_token(self) -> None:  # pragma: no cover - intentionally a no-op
        """Skip token validation in offline tests."""


def _git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run a git command and return its stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout


def _setup_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Initialize a working repo with a bare remote. Returns (work, remote)."""
    work = tmp_path / "work"
    work.mkdir()
    remote = tmp_path / "remote.git"
    remote.mkdir()

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    _git(["init", "--bare"], cwd=remote)
    _git(["init", "-b", "main"], cwd=work)
    (work / "README.md").write_text("hello\n")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", "Initial commit"], cwd=work, env=git_env)
    _git(["remote", "add", "origin", str(remote)], cwd=work)
    _git(["push", "-u", "origin", "main"], cwd=work)

    return work, remote


def _make_worktree(work: Path, branch: str, tmp_path: Path) -> Path:
    """Create a worktree based on origin/main for the given branch.

    If a local branch with the same name already exists (e.g. from a
    previously-removed worktree) it is deleted first so we always start
    from a fresh origin/main base.
    """
    wt_path = tmp_path / f"wt-{branch}-{os.urandom(4).hex()}"
    _git(["fetch", "origin", "main"], cwd=work)
    # Delete existing local branch if present so -b can re-create it
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=work,
        capture_output=True,
        check=False,
    )
    _git(
        ["worktree", "add", str(wt_path), "-b", branch, "origin/main"],
        cwd=work,
    )
    return wt_path


class TestCommitChangesSkipsRedundantPush:
    """Verify commit_changes skips force push when only timestamps would change."""

    def test_skips_push_when_only_timestamps_differ(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Second identical update should not move the remote branch SHA.

        The two commits must have different author/committer dates so that
        without the skip logic they would resolve to distinct SHAs and the
        force push would visibly advance the remote branch.
        """
        work, _remote = _setup_repo_with_remote(tmp_path)
        svc = OfflineGiteaService()
        original_cwd = Path.cwd()
        os.chdir(work)
        try:
            # First run: change a file, commit, push at one date
            monkeypatch.setenv("GIT_AUTHOR_DATE", "2025-01-01T00:00:00+0000")
            monkeypatch.setenv("GIT_COMMITTER_DATE", "2025-01-01T00:00:00+0000")
            wt1 = _make_worktree(work, "update-foo", tmp_path)
            (wt1 / "data.txt").write_text("v2\n")
            assert svc.commit_changes("update-foo", "Update foo", wt1) is True

            first_sha = _git(["rev-parse", "origin/update-foo"], cwd=work).strip()
            _git(["worktree", "remove", "--force", str(wt1)], cwd=work)

            # Second run: produce the same file change but at a later date.
            monkeypatch.setenv("GIT_AUTHOR_DATE", "2025-02-02T00:00:00+0000")
            monkeypatch.setenv("GIT_COMMITTER_DATE", "2025-02-02T00:00:00+0000")
            wt2 = _make_worktree(work, "update-foo", tmp_path)
            (wt2 / "data.txt").write_text("v2\n")

            assert svc.commit_changes("update-foo", "Update foo", wt2) is True

            # Remote SHA must be unchanged - no force push happened
            second_sha = _git(["rev-parse", "origin/update-foo"], cwd=work).strip()
            assert first_sha == second_sha
        finally:
            os.chdir(original_cwd)

    def test_pushes_when_message_differs(self, tmp_path: Path) -> None:
        """Different commit message should still force push (history differs)."""
        work, _remote = _setup_repo_with_remote(tmp_path)
        svc = OfflineGiteaService()
        original_cwd = Path.cwd()
        os.chdir(work)
        try:
            wt1 = _make_worktree(work, "update-bar", tmp_path)
            (wt1 / "data.txt").write_text("v2\n")
            assert svc.commit_changes("update-bar", "Update bar", wt1) is True
            first_sha = _git(["rev-parse", "origin/update-bar"], cwd=work).strip()
            _git(["worktree", "remove", "--force", str(wt1)], cwd=work)

            wt2 = _make_worktree(work, "update-bar", tmp_path)
            (wt2 / "data.txt").write_text("v2\n")
            assert svc.commit_changes("update-bar", "Update bar v2", wt2) is True

            second_sha = _git(["rev-parse", "origin/update-bar"], cwd=work).strip()
            assert first_sha != second_sha
        finally:
            os.chdir(original_cwd)

    def test_pushes_when_parent_differs(self, tmp_path: Path) -> None:
        """Same tree+message but different parent should still force push."""
        work, _remote = _setup_repo_with_remote(tmp_path)
        svc = OfflineGiteaService()
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        original_cwd = Path.cwd()
        os.chdir(work)
        try:
            # First run from current main
            wt1 = _make_worktree(work, "update-baz", tmp_path)
            (wt1 / "data.txt").write_text("v2\n")
            assert svc.commit_changes("update-baz", "Update baz", wt1) is True
            first_sha = _git(["rev-parse", "origin/update-baz"], cwd=work).strip()
            _git(["worktree", "remove", "--force", str(wt1)], cwd=work)

            # Advance main with an unrelated commit
            (work / "other.txt").write_text("unrelated\n")
            _git(["add", "."], cwd=work)
            _git(["commit", "-m", "Unrelated"], cwd=work, env=git_env)
            _git(["push", "origin", "main"], cwd=work)

            # Second run now bases off the new main - same tree contents
            # for data.txt but different parent
            wt2 = _make_worktree(work, "update-baz", tmp_path)
            (wt2 / "data.txt").write_text("v2\n")
            assert svc.commit_changes("update-baz", "Update baz", wt2) is True

            second_sha = _git(["rev-parse", "origin/update-baz"], cwd=work).strip()
            assert first_sha != second_sha
        finally:
            os.chdir(original_cwd)

