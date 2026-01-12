"""Service for managing Nix flake operations."""

import fnmatch
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import FlakeServiceError

logger = logging.getLogger(__name__)


@dataclass
class Flake:
    """Represents a Nix flake file with its inputs."""

    file_path: str
    inputs: list[str] = field(default_factory=list)
    excluded_outputs: list[str] = field(default_factory=list)


class FlakeService:
    """Service for discovering and updating Nix flakes."""

    def discover_flake_files(self, exclude_patterns: str = "") -> list[Flake]:
        """Discover all flake.nix files in the repository.

        Args:
            exclude_patterns: Comma-separated list of glob patterns to exclude

        Returns:
            List of Flake objects found in the repository

        """
        try:
            # Find all flake.nix files
            all_flake_files = list(Path().rglob("flake.nix"))

            # Remove common ignore patterns
            all_flake_files = [
                f
                for f in all_flake_files
                if not any(part in f.parts for part in ["node_modules", ".git", "__pycache__"])
            ]

            exclude_list = (
                [p.strip() for p in exclude_patterns.split(",") if p.strip()]
                if exclude_patterns
                else []
            )
            logger.info("Exclude patterns: %s", exclude_list)

            flakes: list[Flake] = []

            for file in all_flake_files:
                # Check if this file should be completely excluded
                should_exclude_file = False
                excluded_outputs = []

                for pattern in exclude_list:
                    if "#" in pattern:
                        file_pattern, output_name = pattern.split("#", 1)
                        if self._match_pattern(file_pattern, str(file)):
                            excluded_outputs.append(output_name)
                    elif self._match_pattern(pattern, str(file)):
                        should_exclude_file = True
                        break

                if not should_exclude_file:
                    # Check if lock file exists
                    lock_file_path = self._get_flake_lock_path(str(file))
                    if not Path(lock_file_path).exists():
                        logger.info(
                            "Skipping %s - no lock file found at %s",
                            file,
                            lock_file_path,
                        )
                        continue

                    # Get inputs for this flake
                    temp_flake = Flake(str(file), [], excluded_outputs)
                    inputs = self.get_flake_inputs(temp_flake)

                    flakes.append(Flake(str(file), inputs, excluded_outputs))

            logger.info("Found %d flake files after exclusions", len(flakes))
        except Exception as e:
            msg = f"Failed to discover flake files: {e}"
            raise FlakeServiceError(msg) from e
        else:
            return flakes

    def get_flake_inputs(self, flake: Flake) -> list[str]:
        """Get the inputs for a flake file.

        Args:
            flake: The Flake object to get inputs for

        Returns:
            List of input names

        """
        try:
            flake_path = Path(flake.file_path)
            flake_dir = flake_path.parent or Path()

            # Use nix flake metadata to get inputs
            cmd = [
                "nix",
                "flake",
                "metadata",
                "--json",
                "--no-write-lock-file",
            ]
            result = subprocess.run(
                cmd,
                cwd=str(flake_dir),
                capture_output=True,
                text=True,
                check=True,
            )

            metadata = json.loads(result.stdout)
            input_names: list[str] = []

            # Extract input names from the locks section
            if metadata.get("locks") and metadata["locks"].get("nodes"):
                nodes = metadata["locks"]["nodes"]
                root_node = nodes.get("root", {})
                root_inputs = root_node.get("inputs", {})

                # Get all direct inputs of root
                input_names.extend(
                    node_name
                    for node_name in nodes
                    if node_name != "root" and node_name in root_inputs
                )

            logger.info(
                "Found inputs in %s: %s",
                flake.file_path,
                ", ".join(input_names),
            )

            # Filter out excluded outputs for this specific file
            return [name for name in input_names if name not in flake.excluded_outputs]
        except subprocess.CalledProcessError as e:
            msg = f"Failed to parse flake inputs from {flake.file_path}: {e.stderr}"
            raise FlakeServiceError(msg) from e
        except Exception as e:
            msg = f"Failed to parse flake inputs from {flake.file_path}: {e}"
            raise FlakeServiceError(msg) from e

    def update_flake_input(
        self,
        input_name: str,
        flake_file: str,
        work_dir: str | None = None,
    ) -> None:
        """Update a specific flake input.

        Args:
            input_name: Name of the input to update
            flake_file: Path to the flake file
            work_dir: Optional working directory to resolve flake file path from

        """
        try:
            logger.info("Updating flake input: %s in %s", input_name, flake_file)

            # If work_dir is provided, resolve the flake file relative to it
            absolute_flake_path = Path(work_dir) / flake_file if work_dir else Path(flake_file)

            flake_dir = absolute_flake_path.parent or Path()
            absolute_flake_dir = flake_dir.resolve()

            # Use nix flake update to update specific input
            # The shallow URL is needed because we may not have the full history
            # of the git repository (e.g., when using shallow checkouts or worktrees)
            result = subprocess.run(
                [
                    "nix",
                    "flake",
                    "update",
                    "--flake",
                    f"git+file://{absolute_flake_dir}?shallow=1",
                    input_name,
                ],
                cwd=str(flake_dir),
                capture_output=True,
                text=True,
                check=True,
            )

            # Check if there was a warning about non-existent input
            if result.stderr and "does not match any input" in result.stderr:
                logger.warning(
                    "Failed to update input %s in %s: %s",
                    input_name,
                    flake_file,
                    result.stderr.strip(),
                )

            logger.info(
                "Successfully updated flake input: %s in %s",
                input_name,
                flake_file,
            )
        except subprocess.CalledProcessError as e:
            stderr_output = e.stderr.strip() if e.stderr else "No stderr output"
            stdout_output = e.stdout.strip() if e.stdout else "No stdout output"
            logger.exception(
                "Failed to update flake input %s in %s. Exit code: %d\nStdout: %s\nStderr: %s",
                input_name,
                flake_file,
                e.returncode,
                stdout_output,
                stderr_output,
            )
            msg = (
                f"Failed to update flake input {input_name} in {flake_file}: {e}\n"
                f"Stderr: {stderr_output}"
            )
            raise FlakeServiceError(msg) from e
        except Exception as e:
            msg = f"Failed to update flake input {input_name} in {flake_file}: {e}"
            raise FlakeServiceError(msg) from e

    def _get_flake_lock_path(self, flake_file: str) -> str:
        """Get the path to the flake.lock file for a given flake.nix."""
        flake_path = Path(flake_file)
        return str(flake_path.parent / "flake.lock")

    def _match_pattern(self, pattern: str, path: str) -> bool:
        """Match a glob pattern against a path."""
        return fnmatch.fnmatch(path, pattern)
