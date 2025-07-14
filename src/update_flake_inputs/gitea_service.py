"""Service for interacting with Gitea API."""

import contextlib
import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import APIError, GiteaServiceError

logger = logging.getLogger(__name__)


@dataclass
class Branch:
    """Represents a Git branch."""

    name: str
    sha: str


@dataclass
class PullRequest:
    """Represents a pull request."""

    id: int
    number: int
    state: str
    title: str
    body: str
    head: str
    base: str
    html_url: str


class GiteaService:
    """Service for interacting with Gitea repositories and API."""

    def __init__(self, api_url: str, token: str, owner: str, repo: str) -> None:
        """Initialize the Gitea service.

        Args:
            api_url: Base URL for the Gitea API
            token: Authentication token
            owner: Repository owner
            repo: Repository name

        """
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.owner = owner
        self.repo = repo

    @contextlib.contextmanager
    def worktree(self, branch_name: str) -> Iterator[Path]:
        """Context manager for creating and cleaning up a git worktree.

        Args:
            branch_name: Name of the branch to create worktree for

        Yields:
            Path to the worktree directory

        """
        worktree_path = None
        try:
            with tempfile.TemporaryDirectory(prefix="flake-update-") as temp_dir:
                worktree_path = Path(temp_dir) / branch_name

                # Create worktree
                subprocess.run(
                    [
                        "git",
                        "worktree",
                        "add",
                        str(worktree_path),
                        "-b",
                        branch_name,
                    ],
                    check=True,
                )

                logger.info(
                    "Created worktree for branch %s at %s",
                    branch_name,
                    worktree_path,
                )
                yield worktree_path
        finally:
            if worktree_path:
                # Clean up worktree
                with contextlib.suppress(subprocess.SubprocessError, OSError):
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        check=False,
                        capture_output=True,
                    )
                logger.info("Cleaned up worktree at %s", worktree_path)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, object] | None = None,
    ) -> Any:  # noqa: ANN401
        """Make an authenticated request to the Gitea API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Optional data to send with the request

        Returns:
            Parsed JSON response

        Raises:
            APIError: If the request fails

        """
        url = f"{self.api_url}/api/v1{endpoint}"
        assert url.startswith(  # noqa: S101
            ("http://", "https://"),
        ), "URL must use http or https scheme"

        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        request = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310

        if data:
            request.data = json.dumps(data).encode("utf-8")

        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            msg = f"API request failed: {e.code} {e.reason} - {error_body}"
            raise APIError(msg, e.code) from e
        except (urllib.error.URLError, OSError) as e:
            msg = f"API request failed: {e}"
            raise APIError(msg) from e

    def get_branch(self, branch_name: str) -> Branch | None:
        """Get information about a branch.

        Args:
            branch_name: Name of the branch

        Returns:
            Branch object or None if not found

        """
        try:
            endpoint = f"/repos/{self.owner}/{self.repo}/branches/{branch_name}"
            response = self._make_request("GET", endpoint)
            return Branch(
                name=response["name"],
                sha=response["commit"]["id"],
            )
        except APIError:
            return None

    def _ensure_base_branch_exists(self, base_branch: str) -> Branch:
        """Ensure that the base branch exists.

        Args:
            base_branch: Name of the base branch

        Returns:
            Branch object

        Raises:
            GiteaServiceError: If branch not found

        """
        base = self.get_branch(base_branch)
        if not base:
            msg = f"Base branch {base_branch} not found"
            raise GiteaServiceError(msg)
        return base

    def create_branch(self, branch_name: str, base_branch: str) -> None:
        """Create a new branch.

        Args:
            branch_name: Name for the new branch
            base_branch: Base branch to create from

        """
        # Get base branch info
        self._ensure_base_branch_exists(base_branch)

        # Check if branch already exists
        existing = self.get_branch(branch_name)
        if existing:
            # Delete the existing branch
            endpoint = f"/repos/{self.owner}/{self.repo}/branches/{branch_name}"
            try:
                self._make_request("DELETE", endpoint)
                logger.info("Deleted existing branch: %s", branch_name)
            except APIError:
                logger.warning("Failed to delete existing branch: %s", branch_name)

        # Create new branch via API
        endpoint = f"/repos/{self.owner}/{self.repo}/branches"
        request_data: dict[str, object] = {
            "new_branch_name": branch_name,
            "old_ref_name": base_branch,
        }
        self._make_request("POST", endpoint, request_data)
        logger.info("Created branch %s from %s", branch_name, base_branch)

    def commit_changes(
        self,
        branch_name: str,
        commit_message: str,
        worktree_path: Path,
    ) -> bool:
        """Commit and push changes in a worktree.

        Args:
            branch_name: Name of the branch
            commit_message: Commit message
            worktree_path: Path to the worktree

        Returns:
            True if changes were committed, False if no changes

        """
        # Add all changes in the worktree
        subprocess.run(
            ["git", "add", "."],
            cwd=worktree_path,
            check=True,
        )

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            check=False,
            cwd=worktree_path,
            capture_output=True,
        )

        # Exit code 0 = no changes, exit code 1 = has changes
        has_changes = result.returncode != 0

        if not has_changes:
            logger.info("No changes to commit")
            return False

        # Commit changes
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "gitea-actions[bot]",
                "GIT_AUTHOR_EMAIL": "gitea-actions[bot]@noreply.gitea.io",
                "GIT_COMMITTER_NAME": "gitea-actions[bot]",
                "GIT_COMMITTER_EMAIL": "gitea-actions[bot]@noreply.gitea.io",
            }
        )

        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=worktree_path,
            env=env,
            check=True,
        )

        # Push to remote
        subprocess.run(
            ["git", "push", "origin", branch_name],
            cwd=worktree_path,
            check=True,
        )

        logger.info("Committed and pushed changes to branch: %s", branch_name)
        return True

    def create_pull_request(
        self,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> None:
        """Create a pull request.

        Args:
            branch_name: Source branch
            base_branch: Target branch
            title: PR title
            body: PR description

        """
        # Check if PR already exists
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls"
        params = urllib.parse.urlencode(
            {
                "state": "open",
                "head": branch_name,
                "base": base_branch,
            }
        )
        existing_prs: list[Any] = self._make_request("GET", f"{endpoint}?{params}")

        if existing_prs:
            logger.info("Pull request already exists for branch: %s", branch_name)
            return

        # Create pull request
        request_data: dict[str, object] = {
            "base": base_branch,
            "head": branch_name,
            "title": title,
            "body": body,
        }
        pr: dict[str, Any] = self._make_request("POST", endpoint, request_data)

        logger.info("Created pull request #%d: %s", pr["number"], pr["html_url"])
