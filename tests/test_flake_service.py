"""Tests for FlakeService based on TypeScript test scenarios."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from update_flake_inputs.flake_service import FlakeService


class TestFlakeService:
    """Test cases for FlakeService."""

    @pytest.fixture
    def flake_service(self) -> FlakeService:
        """Create a FlakeService instance."""
        return FlakeService()

    @pytest.fixture
    def fixtures_path(self) -> Path:
        """Get path to test fixtures."""
        return Path(__file__).parent / "fixtures"

    def test_discover_flake_files(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test discovering all flake.nix files and their inputs."""
        # Change to fixtures directory
        monkeypatch.chdir(fixtures_path)

        # Discover flakes
        flakes = flake_service.discover_flake_files()

        # Should find simple/flake.nix, minimal/flake.nix, subflake/flake.nix
        # and subflake/sub/flake.nix
        min_expected_flakes = 4
        assert len(flakes) >= min_expected_flakes

        # Find the simple flake
        simple_flake = next(
            (f for f in flakes if f.file_path == "simple/flake.nix"), None
        )
        assert simple_flake is not None
        assert "nixos-hardware" in simple_flake.inputs
        assert "flake-utils" in simple_flake.inputs
        simple_flake_input_count = 2
        assert len(simple_flake.inputs) == simple_flake_input_count

        # Find the root subflake
        root_subflake = next(
            (f for f in flakes if f.file_path == "subflake/flake.nix"), None
        )
        assert root_subflake is not None
        assert "flake-utils" in root_subflake.inputs
        assert len(root_subflake.inputs) == 1

        # Find the nested subflake
        nested_subflake = next(
            (f for f in flakes if f.file_path == "subflake/sub/flake.nix"), None
        )
        assert nested_subflake is not None
        assert "flake-utils" in nested_subflake.inputs
        assert "nixos-hardware" in nested_subflake.inputs
        nested_subflake_input_count = 2
        assert len(nested_subflake.inputs) == nested_subflake_input_count

        # Find the minimal flake
        minimal_flake = next(
            (f for f in flakes if f.file_path == "minimal/flake.nix"), None
        )
        assert minimal_flake is not None
        assert "flake-utils" in minimal_flake.inputs
        assert len(minimal_flake.inputs) == 1

        # Verify that flakes without lock files are skipped
        no_lock_flake = next(
            (f for f in flakes if f.file_path == "no-lock/flake.nix"), None
        )
        assert no_lock_flake is None

        # Verify that flakes with local inputs are skipped
        local_flake = next(
            (f for f in flakes if f.file_path == "local-flake-repo/flake.nix"), None
        )
        assert local_flake is None

    def test_discover_flake_files_with_exclude_patterns(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test respecting exclude patterns for files."""
        monkeypatch.chdir(fixtures_path)

        # Exclude all subflake files
        flakes = flake_service.discover_flake_files("subflake/**")

        # Should exclude all subflake files
        subflake_files = [f for f in flakes if f.file_path.startswith("subflake/")]
        assert len(subflake_files) == 0

        # Should still include simple/flake.nix
        simple_flake = next(
            (f for f in flakes if f.file_path == "simple/flake.nix"), None
        )
        assert simple_flake is not None

    def test_discover_flake_files_with_input_excludes(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test respecting exclude patterns for specific inputs."""
        monkeypatch.chdir(fixtures_path)

        # Exclude flake-utils input from all flakes
        flakes = flake_service.discover_flake_files("**/flake.nix#flake-utils")

        # All flakes should still be discovered
        min_expected_flakes = 4
        assert len(flakes) >= min_expected_flakes

        # But flake-utils should be excluded from all inputs
        for flake in flakes:
            assert "flake-utils" not in flake.inputs

        # Other inputs should still be present
        simple_flake = next(
            (f for f in flakes if f.file_path == "simple/flake.nix"), None
        )
        assert simple_flake is not None
        assert "nixos-hardware" in simple_flake.inputs

        nested_subflake = next(
            (f for f in flakes if f.file_path == "subflake/sub/flake.nix"), None
        )
        assert nested_subflake is not None
        assert "nixos-hardware" in nested_subflake.inputs

    def test_discover_flake_files_with_mixed_excludes(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test handling mixed exclude patterns."""
        monkeypatch.chdir(fixtures_path)

        # Exclude simple/** completely and nixos-hardware from subflake/sub/flake.nix
        flakes = flake_service.discover_flake_files(
            "simple/**,subflake/sub/flake.nix#nixos-hardware"
        )

        # simple/flake.nix should be completely excluded
        simple_flake = next(
            (f for f in flakes if f.file_path == "simple/flake.nix"), None
        )
        assert simple_flake is None

        # subflake/sub/flake.nix should exist but without nixos-hardware
        nested_subflake = next(
            (f for f in flakes if f.file_path == "subflake/sub/flake.nix"), None
        )
        assert nested_subflake is not None
        assert "flake-utils" in nested_subflake.inputs
        assert "nixos-hardware" not in nested_subflake.inputs

    def test_update_flake_input(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
    ) -> None:
        """Test updating a flake input and modifying the lock file."""
        # Create a temporary directory for the test
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy minimal flake to temp directory
            shutil.copy(
                fixtures_path / "minimal" / "flake.nix",
                temp_path / "flake.nix",
            )
            shutil.copy(
                fixtures_path / "minimal" / "flake.lock",
                temp_path / "flake.lock",
            )

            # Initialize git repo in temp directory
            subprocess.run(["git", "init"], cwd=temp_path, check=True)
            subprocess.run(["git", "add", "."], cwd=temp_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=temp_path,
                check=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test User",
                    "GIT_AUTHOR_EMAIL": "test@example.com",
                    "GIT_COMMITTER_NAME": "Test User",
                    "GIT_COMMITTER_EMAIL": "test@example.com",
                },
            )

            # Get the original lock file content
            original_lock_content = (temp_path / "flake.lock").read_text()
            original_lock = json.loads(original_lock_content)
            original_flake_utils_rev = original_lock["nodes"]["flake-utils"]["locked"][
                "rev"
            ]

            # Update flake-utils input
            flake_service.update_flake_input("flake-utils", "flake.nix", str(temp_path))

            # Check that the lock file was modified
            updated_lock_content = (temp_path / "flake.lock").read_text()
            updated_lock = json.loads(updated_lock_content)

            # The lock file should have changed
            assert updated_lock_content != original_lock_content

            # The flake-utils input should still exist
            assert "flake-utils" in updated_lock["nodes"]
            assert updated_lock["nodes"]["flake-utils"]["locked"]["owner"] == "numtide"
            assert (
                updated_lock["nodes"]["flake-utils"]["locked"]["repo"] == "flake-utils"
            )
            assert "rev" in updated_lock["nodes"]["flake-utils"]["locked"]
            assert "narHash" in updated_lock["nodes"]["flake-utils"]["locked"]

            # The revision should have changed from our old one
            assert (
                updated_lock["nodes"]["flake-utils"]["locked"]["rev"]
                != original_flake_utils_rev
            )

    def test_update_nonexistent_input(
        self,
        flake_service: FlakeService,
        fixtures_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling updating a non-existent input gracefully."""
        # Create a temporary directory for the test
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy minimal flake to temp directory
            shutil.copy(
                fixtures_path / "minimal" / "flake.nix",
                temp_path / "flake.nix",
            )
            shutil.copy(
                fixtures_path / "minimal" / "flake.lock",
                temp_path / "flake.lock",
            )

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=temp_path, check=True)
            subprocess.run(["git", "add", "."], cwd=temp_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=temp_path,
                check=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test User",
                    "GIT_AUTHOR_EMAIL": "test@example.com",
                    "GIT_COMMITTER_NAME": "Test User",
                    "GIT_COMMITTER_EMAIL": "test@example.com",
                },
            )

            original_lock_content = (temp_path / "flake.lock").read_text()

            # This should not throw an error, just log a warning
            flake_service.update_flake_input("nonexistent", "flake.nix", str(temp_path))

            # The lock file should remain unchanged
            current_lock_content = (temp_path / "flake.lock").read_text()
            assert current_lock_content == original_lock_content

            # Check that a warning was logged
            assert any(
                "Failed to update input nonexistent" in record.message
                for record in caplog.records
            )
