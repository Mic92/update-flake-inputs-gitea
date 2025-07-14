{
  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self, flake-utils }:
    {
      # Flake without lock file
    };
}
