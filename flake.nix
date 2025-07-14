{
  description = "Update Nix flake inputs and create pull requests on Gitea";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix.url = "github:numtide/treefmt-nix";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [
        inputs.treefmt-nix.flakeModule
      ];

      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      perSystem =
        { config, pkgs, ... }:
        {
          packages.update-flake-inputs = pkgs.callPackage ./package.nix { };
          packages.default = config.packages.update-flake-inputs;

          devShells.default = pkgs.callPackage ./shell.nix {
            inherit (config.packages) update-flake-inputs;
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs = {
              nixfmt.enable = true;
              ruff.format = true;
              ruff.check = true;
            };
          };
        };
    };
}
