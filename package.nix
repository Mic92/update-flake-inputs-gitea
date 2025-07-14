{
  lib,
  python313,
  git,
  nix,
}:

let
  python = python313;
in
python.pkgs.buildPythonApplication {
  pname = "update-flake-inputs";
  version = "0.1.0";
  format = "pyproject";

  src = ./.;

  nativeBuildInputs = with python.pkgs; [
    hatchling
  ];

  propagatedBuildInputs = [
    git
    nix
  ];

  doCheck = false;

  meta = {
    description = "Gitea Action to update Nix flake inputs and create pull requests";
    license = lib.licenses.mit;
    mainProgram = "update-flake-inputs";
  };
}
