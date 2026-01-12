"""Command line interface for update-flake-inputs."""

import argparse
import logging
import os
import sys
from pathlib import Path

from .exceptions import UpdateFlakeInputsError
from .flake_service import FlakeService
from .gitea_service import GiteaService

logger = logging.getLogger(__name__)


def setup_logging(*, verbose: bool = False) -> None:
    """Set up logging configuration.

    Args:
        verbose: Whether to enable verbose logging

    """
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=level, format=format_str)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments

    """
    parser = argparse.ArgumentParser(
        description="Update Nix flake inputs and create pull requests on Gitea"
    )

    parser.add_argument(
        "--gitea-url",
        default=os.environ.get("GITEA_URL", ""),
        help="Gitea server URL (defaults to GITEA_URL env var)",
    )

    parser.add_argument(
        "--gitea-token",
        default=os.environ.get("GITEA_TOKEN", ""),
        help="Gitea authentication token (defaults to GITEA_TOKEN env var)",
    )

    parser.add_argument(
        "--gitea-repository",
        default=os.environ.get("GITEA_REPOSITORY", ""),
        help="Repository in format owner/repo (defaults to GITEA_REPOSITORY env var)",
    )

    parser.add_argument(
        "--exclude-patterns",
        default=os.environ.get("EXCLUDE_PATTERNS", ""),
        help="Comma-separated list of glob patterns to exclude flake.nix files",
    )

    parser.add_argument(
        "--base-branch",
        default="main",
        help="Base branch to create PRs against (default: main)",
    )

    parser.add_argument(
        "--branch-suffix",
        default=os.environ.get("BRANCH_SUFFIX", ""),
        help="Optional suffix to append to update branches (default: empty)",
    )

    parser.add_argument(
        "--auto-merge",
        action="store_true",
        help="Automatically merge PRs when checks succeed",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--git-author-name",
        default=os.environ.get("GIT_AUTHOR_NAME", "gitea-actions[bot]"),
        help="Git author name (defaults to GIT_AUTHOR_NAME env var or 'gitea-actions[bot]')",
    )

    parser.add_argument(
        "--git-author-email",
        default=os.environ.get("GIT_AUTHOR_EMAIL", "gitea-actions[bot]@noreply.gitea.io"),
        help=(
            "Git author email (defaults to GIT_AUTHOR_EMAIL env var "
            "or 'gitea-actions[bot]@noreply.gitea.io')"
        ),
    )

    parser.add_argument(
        "--git-committer-name",
        default=os.environ.get("GIT_COMMITTER_NAME", "gitea-actions[bot]"),
        help="Git committer name (defaults to GIT_COMMITTER_NAME env var or 'gitea-actions[bot]')",
    )

    parser.add_argument(
        "--git-committer-email",
        default=os.environ.get("GIT_COMMITTER_EMAIL", "gitea-actions[bot]@noreply.gitea.io"),
        help=(
            "Git committer email (defaults to GIT_COMMITTER_EMAIL env var "
            "or 'gitea-actions[bot]@noreply.gitea.io')"
        ),
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Validate command line arguments.

    Args:
        args: Parsed arguments

    Raises:
        SystemExit: If validation fails

    """
    if not args.gitea_url:
        logger.error("Gitea URL is required (--gitea-url or GITEA_URL env var)")
        sys.exit(1)

    if not args.gitea_token:
        logger.error("Gitea token is required (--gitea-token or GITEA_TOKEN env var)")
        sys.exit(1)

    if not args.gitea_repository:
        logger.error(
            "Gitea repository is required (--gitea-repository or GITEA_REPOSITORY env var)"
        )
        sys.exit(1)

    if "/" not in args.gitea_repository:
        logger.error(
            "Repository must be in format owner/repo, got: %s",
            args.gitea_repository,
        )
        sys.exit(1)


def process_flake_updates(  # noqa: PLR0913
    flake_service: FlakeService,
    gitea_service: GiteaService,
    exclude_patterns: str,
    base_branch: str,
    branch_suffix: str,
    *,
    auto_merge: bool,
) -> None:
    """Process all flake updates.

    Args:
        flake_service: Flake service instance
        gitea_service: Gitea service instance
        exclude_patterns: Patterns to exclude
        base_branch: Base branch for PRs
        branch_suffix: Optional suffix to append to branch names
        auto_merge: Whether to automatically merge PRs

    """
    # Discover flake files
    flakes = flake_service.discover_flake_files(exclude_patterns)
    if not flakes:
        logger.info("No flake files found")
        return

    logger.info("Found %d flake files to process", len(flakes))

    # Process each flake
    for flake in flakes:
        logger.info("Processing flake: %s", flake.file_path)
        logger.info("Inputs to update: %s", ", ".join(flake.inputs))

        # Update each input
        for input_name in flake.inputs:
            try:
                # Generate branch name - don't include '.' for root directory
                parent_path = Path(flake.file_path).parent
                if parent_path == Path():
                    branch_name = f"update-{input_name}"
                else:
                    branch_name = f"update-{parent_path}-{input_name}"
                branch_name = branch_name.replace("/", "-").strip("-")
                suffix = branch_suffix.strip().replace("/", "-").strip("-")
                if suffix:
                    branch_name = f"{branch_name}-{suffix}"

                logger.info(
                    "Updating input %s in %s (branch: %s)",
                    input_name,
                    flake.file_path,
                    branch_name,
                )

                # Create worktree and update input
                with gitea_service.worktree(branch_name) as worktree_path:
                    # Update the input
                    flake_service.update_flake_input(
                        input_name,
                        flake.file_path,
                        str(worktree_path),
                    )

                    # Commit changes
                    parent_path = Path(flake.file_path).parent
                    if parent_path == Path():
                        commit_message = f"Update {input_name}"
                    else:
                        commit_message = f"Update {input_name} in {parent_path}"
                    if gitea_service.commit_changes(
                        branch_name,
                        commit_message,
                        worktree_path,
                    ):
                        # Create pull request
                        pr_title = commit_message
                        pr_body = (
                            f"This PR updates the `{input_name}` input "
                            f"in `{flake.file_path}`.\n\n"
                            "Generated by update-flake-inputs action."
                        )
                        gitea_service.create_pull_request(
                            branch_name,
                            base_branch,
                            pr_title,
                            pr_body,
                            auto_merge=auto_merge,
                        )
                    else:
                        logger.info(
                            "No changes for input %s in %s",
                            input_name,
                            flake.file_path,
                        )

            except Exception:
                logger.exception(
                    "Failed to update input %s in %s",
                    input_name,
                    flake.file_path,
                )
                # Continue with next input


def main() -> None:
    """Run the main program."""
    try:
        args = parse_args()
        setup_logging(verbose=args.verbose)
        validate_args(args)

        # Parse repository
        owner, repo = args.gitea_repository.split("/", 1)

        # Create services
        flake_service = FlakeService()
        gitea_service = GiteaService(
            api_url=args.gitea_url,
            token=args.gitea_token,
            owner=owner,
            repo=repo,
            git_author_name=args.git_author_name,
            git_author_email=args.git_author_email,
            git_committer_name=args.git_committer_name,
            git_committer_email=args.git_committer_email,
        )

        # Process updates
        process_flake_updates(
            flake_service,
            gitea_service,
            args.exclude_patterns,
            args.base_branch,
            args.branch_suffix,
            auto_merge=args.auto_merge,
        )

        logger.info("Completed processing all flake updates")

    except UpdateFlakeInputsError:
        logger.exception("Error")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception:
        logger.exception("Unexpected error")
        sys.exit(1)


if __name__ == "__main__":
    main()
