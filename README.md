# update-flake-inputs-gitea

A Gitea Action that automatically updates Nix flake inputs and creates pull requests.

## Features

- Discovers all `flake.nix` files in your repository
- Updates each flake input individually
- Creates separate pull requests for each input update
- Works with Git worktrees to isolate changes
- Supports excluding specific flake files or inputs
- Auto-merge capability for PRs when checks succeed
- GitHub token support to avoid rate limits

## Requirements

This action requires Nix to be installed on the runner. The action uses `nix run` to execute the flake update logic.
If you have your gitea runner on nixos, you may use this [nixos-module](https://git.clan.lol/clan/clan-infra/src/commit/53a15c0aa8f3d8f4dc1386f92f1dd49255b90bfc/modules/web01/gitea/actions-runner.nix).

## Usage

Add this action to your Gitea repository workflows:

```yaml
name: Update Flake Inputs

on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Update flake inputs
      uses: Mic92/update-flake-inputs-gitea@main
      with:
        gitea-token: ${{ secrets.GITEA_TOKEN }}
```

### Action Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `gitea-url` | Gitea server URL | Yes | `${{ gitea.server_url }}` |
| `gitea-token` | Gitea authentication token | Yes | `${{ secrets.GITEA_TOKEN }}` |
| `gitea-repository` | Repository in format owner/repo | No | `${{ gitea.repository }}` |
| `exclude-patterns` | Comma-separated list of glob patterns to exclude flake.nix files | No | `''` |
| `base-branch` | Base branch to create PRs against | No | `main` |
| `branch-suffix` | Suffix to append to update branches | No | `''` |
| `auto-merge` | Automatically merge PRs when checks succeed | No | `false` |
| `github-token` | GitHub token for avoiding rate limits when fetching flake inputs | No | `''` |
| `git-author-name` | Git author name for commits | No | `gitea-actions[bot]` |
| `git-author-email` | Git author email for commits | No | `gitea-actions[bot]@noreply.gitea.io` |
| `git-committer-name` | Git committer name for commits | No | `gitea-actions[bot]` |
| `git-committer-email` | Git committer email for commits | No | `gitea-actions[bot]@noreply.gitea.io` |

### Advanced Example

```yaml
name: Update Flake Inputs

on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Update flake inputs
      uses: Mic92/update-flake-inputs-gitea@main
      with:
        gitea-token: ${{ secrets.GITEA_TOKEN }}
        base-branch: develop
        auto-merge: true
        github-token: ${{ secrets.GITHUB_TOKEN }}
        exclude-patterns: "tests/**,examples/**"
```

### GitHub Rate Limits

When updating flake inputs that reference GitHub repositories, you may encounter rate limits. To avoid this, provide a GitHub token via the `github-token` input:

```yaml
- name: Update flake inputs
  uses: Mic92/update-flake-inputs-gitea@main
  with:
    gitea-token: ${{ secrets.GITEA_TOKEN }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

This will configure Nix to use the token when fetching from GitHub, significantly increasing the rate limit.

### Custom Git Author/Committer

By default, commits are created with `gitea-actions[bot]` as the author. However, you may want to use a different author to:
- Trigger specific Gitea workflows that filter on commit authors
- Comply with organizational policies
- Use a dedicated bot account for audit trails

You can customize the git author and committer information:

```yaml
- name: Update flake inputs
  uses: Mic92/update-flake-inputs-gitea@main
  with:
    gitea-token: ${{ secrets.GITEA_TOKEN }}
    git-author-name: "My Bot"
    git-author-email: "bot@mycompany.com"
    git-committer-name: "My Bot"
    git-committer-email: "bot@mycompany.com"
```

## Development

### Setup

```bash
nix develop
```

### Running Tests

```bash
pytest
```

### Linting and Formatting

```bash
ruff format .
ruff check .
mypy .
```

## License

MIT
