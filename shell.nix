{
  mkShell,
  python313,
  git,
  nix,
  update-flake-inputs,
}:

let
  python = python313;
in
mkShell {
  inputsFrom = [ update-flake-inputs ];

  packages = [
    git
    nix
    python.pkgs.mypy
    python.pkgs.ruff
    python.pkgs.pytest
    python.pkgs.pytest-cov
    python.pkgs.hatchling
  ];

  shellHook = ''
    echo "Update Flake Inputs development shell"
    echo "Python: ${python.name}"
    echo ""
    echo "Available commands:"
    echo "  ruff format .      - Format code"
    echo "  ruff check .       - Lint code"
    echo "  mypy .             - Type check code"
    echo "  pytest             - Run tests"
    echo "  python -m update_flake_inputs - Run the tool"
  '';
}
