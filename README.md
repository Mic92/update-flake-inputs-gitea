# update-flake-inputs-gitea

A Gitea Action that automatically updates Nix flake inputs and creates pull requests.

## Features

- Discovers all `flake.nix` files in your repository
- Updates each flake input individually
- Creates separate pull requests for each input update
- Works with Git worktrees to isolate changes
- Supports excluding specific flake files or inputs

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
