"""Service for interacting with Gitea API."""

import contextlib
import json
import logging
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import APIError

logger = logging.getLogger(__name__)

# HTTP Status Codes
HTTP_CONFLICT = 409


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


@dataclass
class GiteaService:
    """Service for interacting with Gitea repositories and API."""

    api_url: str
    token: str
    owner: str
    repo: str
    git_author_name: str = "gitea-actions[bot]"
    git_author_email: str = "gitea-actions[bot]@noreply.gitea.io"
    git_committer_name: str = "gitea-actions[bot]"
    git_committer_email: str = "gitea-actions[bot]@noreply.gitea.io"

    def __post_init__(self) -> None:
        """Post-initialization processing."""
        # Clean up the API URL
        self.api_url = self.api_url.rstrip("/")

        # Validate token and log authenticated user
        self._validate_token()

    def _validate_token(self) -> None:
        """Validate the token and log the authenticated user.

        Raises:
            APIError: If token validation fails

        """
        try:
            user_info = self._make_request("GET", "/user")
            logger.info(
                "Authenticated as user: %s",
                user_info.get("login", "unknown"),
            )

            # Also check repository access
            repo_info = self._make_request("GET", f"/repos/{self.owner}/{self.repo}")
            logger.info(
                "Repository %s/%s - permissions: %s",
                self.owner,
                self.repo,
                repo_info.get("permissions", {}),
            )
        except APIError:
            logger.exception("Failed to validate token")
            raise

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
                "GIT_AUTHOR_NAME": self.git_author_name,
                "GIT_AUTHOR_EMAIL": self.git_author_email,
                "GIT_COMMITTER_NAME": self.git_committer_name,
                "GIT_COMMITTER_EMAIL": self.git_committer_email,
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
            ["git", "push", "origin", "--force", branch_name],
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
        *,
        auto_merge: bool = False,
    ) -> None:
        """Create a pull request.

        Args:
            branch_name: Source branch
            base_branch: Target branch
            title: PR title
            body: PR description
            auto_merge: Whether to automatically merge when checks succeed

        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls"

        # Create pull request
        request_data: dict[str, object] = {
            "base": base_branch,
            "head": branch_name,
            "title": title,
            "body": body,
        }

        try:
            pr: dict[str, Any] = self._make_request("POST", endpoint, request_data)
            logger.info("Created pull request #%d: %s", pr["number"], pr["html_url"])
        except APIError as e:
            if e.status_code == HTTP_CONFLICT:
                logger.info("Pull request already exists for branch: %s", branch_name)
            else:
                raise
            return  # Exit early if PR creation failed

        # Auto-merge if requested and PR was created successfully
        if auto_merge:
            try:
                self._merge_pull_request(pr["number"])
            except APIError:
                logger.exception("Failed to auto-merge pull request #%d", pr["number"])
                # Don't re-raise - PR was created successfully

    def _merge_pull_request(self, pr_number: int) -> None:
        """Merge a pull request when checks succeed.

        Args:
            pr_number: Pull request number

        Raises:
            APIError: If merge fails

        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/merge"

        merge_data: dict[str, object] = {
            "Do": "merge",
            "merge_when_checks_succeed": True,
            "delete_branch_after_merge": True,
        }

        # Keep retrying if we get "Please try again later"
        max_retries = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self._make_request("POST", endpoint, merge_data)
            except APIError as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise
                logger.info("Merge request failed, retrying...")
                time.sleep(2)
                continue

            if response.get("message") == "Please try again later":
                if attempt < max_retries - 1:
                    logger.info("Merge not ready, retrying in 2 seconds...")
                    time.sleep(2)
                    continue
                msg = "Max retries reached for merge"
                raise APIError(msg) from last_error

            logger.info("Pull request #%d merge initiated", pr_number)
            return
