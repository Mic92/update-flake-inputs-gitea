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
| `auto-merge` | Automatically merge PRs when checks succeed | No | `false` |
| `github-token` | GitHub token for avoiding rate limits when fetching flake inputs | No | `''` |

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
