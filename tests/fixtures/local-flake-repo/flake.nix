{
  inputs = {
    # Local input that will cause nix flake lock to fail
    local.url = "path:../nonexistent";
  };

  outputs = { self, local }: {
    # Flake with local input
  };
}