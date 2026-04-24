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
        let
          python = pkgs.python313;
          pythonEnv = python.withPackages (
            ps: with ps; [
              config.packages.update-flake-inputs
              pytest
            ]
          );

          mypyEnv = python.withPackages (
            ps: with ps; [
              config.packages.update-flake-inputs
              mypy
              pytest
            ]
          );

          mkPytestCheck =
            {
              impure ? false,
            }:
            pkgs.runCommand "pytest${pkgs.lib.optionalString impure "-impure"}"
              (
                {
                  nativeBuildInputs = [
                    pythonEnv
                    pkgs.git
                    pkgs.nix
                  ]
                  ++ pkgs.lib.optionals impure [ pkgs.cacert ];
                }
                // pkgs.lib.optionalAttrs impure { __impure = true; }
              )
              ''
                cp -r ${./.} ./src
                chmod +w -R ./src
                cd ./src

                # Give the inner nix a private store/state inside $TMPDIR so
                # it can freely add and mutate store paths without needing
                # write access to the outer /nix/store (which the sandboxed
                # build user does not have).
                export HOME=$TMPDIR
                export NIX_STORE_DIR=$TMPDIR/store
                export NIX_STATE_DIR=$TMPDIR/nix
                export NIX_CONF_DIR=$TMPDIR/etc
                mkdir -p "$NIX_STORE_DIR" "$NIX_CONF_DIR"
                echo "experimental-features = nix-command flakes" > "$NIX_CONF_DIR/nix.conf"

                export GIT_AUTHOR_NAME="Test User"
                export GIT_AUTHOR_EMAIL="test@example.com"
                export GIT_COMMITTER_NAME="Test User"
                export GIT_COMMITTER_EMAIL="test@example.com"

                ${pkgs.lib.optionalString impure "export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"}

                python -m pytest ${pkgs.lib.optionalString (!impure) "-m 'not impure'"} tests/

                touch $out
              '';
        in
        {
          packages.update-flake-inputs = pkgs.callPackage ./package.nix { };
          packages.default = config.packages.update-flake-inputs;

          devShells.default = pkgs.callPackage ./shell.nix {
            inherit (config.packages) update-flake-inputs;
          };

          checks.pytest = mkPytestCheck { };
          checks.pytest-impure = mkPytestCheck { impure = true; };

          checks.mypy = pkgs.runCommand "mypy" { nativeBuildInputs = [ mypyEnv ]; } ''
            cp -r ${./.} ./src
            chmod +w -R ./src
            cd ./src

            export HOME=$TMPDIR
            mypy .

            touch $out
          '';

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
