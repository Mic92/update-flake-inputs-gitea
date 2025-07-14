"""Integration tests for process_flake_updates based on TypeScript test scenarios."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from update_flake_inputs.cli import process_flake_updates
from update_flake_inputs.flake_service import FlakeService
from update_flake_inputs.gitea_service import GiteaService


class TestGiteaService(GiteaService):
    def __init__(self) -> None:
        """Initialize test service without API credentials."""
        self.api_url = "https://gitea.example.com"
        self.token = "test-token"  # noqa: S105
        self.owner = "test-owner"
        self.repo = "test-repo"
        self.pr_creation_attempts: list[dict[str, str]] = []
        # Skip token validation in tests

    def _validate_token(self) -> None:
        """Skip token validation in tests."""

    def create_pull_request(
        self,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
        *,
        auto_merge: bool = False,
    ) -> None:
        """Record PR creation attempt without making actual API call."""
        self.pr_creation_attempts.append(
            {
                "branch_name": branch_name,
                "base_branch": base_branch,
                "title": title,
                "body": body,
                "auto_merge": str(auto_merge),
            }
        )


class TestProcessFlakeUpdates:
    """Integration tests for process_flake_updates."""

    @pytest.fixture
    def fixtures_path(self) -> Path:
        """Get path to test fixtures."""
        return Path(__file__).parent / "fixtures"

    def test_with_up_to_date_flake_input(
        self,
        tmp_path: Path,
        fixtures_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that no PR is created when flake input is already up-to-date."""
        # Create a flake with a local input that won't have updates
        flake_content = (fixtures_path / "up-to-date" / "flake.nix").read_text()

        # Replace relative path with absolute path
        absolute_path = fixtures_path / "local-flake-repo"
        patched_content = flake_content.replace(
            "path:../local-flake-repo",
            f"path:{absolute_path}",
        )

        (tmp_path / "flake.nix").write_text(patched_content)

        # Generate lock file
        subprocess.run(["nix", "flake", "lock"], cwd=tmp_path, check=True)

        # Initialize git repo
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=tmp_path,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test User",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test User",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            },
        )

        # Add remote
        remote_dir = tmp_path.parent / f"remote-{tmp_path.name}.git"
        remote_dir.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_dir)],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=tmp_path,
            check=True,
        )

        # Change to test directory
        original_cwd = Path.cwd()
        os.chdir(tmp_path)

        try:
            # Create test services
            flake_service = FlakeService()
            test_gitea_service = TestGiteaService()

            # Set log level for capturing
            caplog.set_level("INFO")

            # Process updates
            process_flake_updates(
                flake_service,
                test_gitea_service,
                "",
                "main",
                auto_merge=False,
            )

            # Verify NO pull request was created
            assert len(test_gitea_service.pr_creation_attempts) == 0

            # Verify we detected no changes
            assert any(
                "No changes for input local-test in flake.nix" in record.message
                for record in caplog.records
            )

            # Verify we're still on main branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == "main"

            # Verify no new commits on main
            result = subprocess.run(
                ["git", "log", "--oneline"],
                capture_output=True,
                text=True,
                check=True,
            )
            commits = result.stdout.strip().split("\n")
            single_commit = 1
            assert len(commits) == single_commit
            assert "Initial commit" in commits[0]

        finally:
            os.chdir(original_cwd)

    def test_with_updatable_flake_input(
        self,
        tmp_path: Path,
        fixtures_path: Path,
    ) -> None:
        """Test PR creation when flake input has available updates."""
        # Create a flake with flake-utils that can be updated
        flake_content = """{
  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, flake-utils }: {
    # Test flake with updatable input
  };
}"""

        (tmp_path / "flake.nix").write_text(flake_content)

        # Copy old lock file from minimal fixture
        shutil.copy(
            fixtures_path / "minimal" / "flake.lock",
            tmp_path / "flake.lock",
        )

        # Initialize git repo
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=tmp_path,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test User",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test User",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            },
        )

        # Add remote
        remote_dir = tmp_path.parent / f"remote-{tmp_path.name}.git"
        remote_dir.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_dir)],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=tmp_path,
            check=True,
        )

        # Change to test directory
        original_cwd = Path.cwd()
        os.chdir(tmp_path)

        try:
            # Create test services
            flake_service = FlakeService()
            test_gitea_service = TestGiteaService()

            # Process updates
            process_flake_updates(
                flake_service,
                test_gitea_service,
                "",
                "main",
                auto_merge=False,
            )

            # Verify pull request was created
            assert len(test_gitea_service.pr_creation_attempts) == 1

            pr_attempt = test_gitea_service.pr_creation_attempts[0]
            assert pr_attempt["branch_name"] == "update-flake-utils"
            assert pr_attempt["base_branch"] == "main"
            assert pr_attempt["title"] == "Update flake-utils"
            assert "updates the `flake-utils` input" in pr_attempt["body"]

            # Verify PR was created with correct information

            # Verify we're back on main branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == "main"

            # Verify the update branch exists and has the commit
            result = subprocess.run(
                ["git", "log", "--oneline", "update-flake-utils"],
                capture_output=True,
                text=True,
                check=True,
            )
            commits = result.stdout.strip().split("\n")
            expected_commits = 2
            assert len(commits) == expected_commits
            assert "Update flake-utils" in commits[0]
            assert "Initial commit" in commits[1]

        finally:
            os.chdir(original_cwd)
