{
  description = "closesource repo flake";

  inputs = {
    proxy-flake.url = "github:winston0410/proxy-flake/main";
    nixpkgs.follows = "proxy-flake/nixpkgs";
    flake-parts.follows = "proxy-flake/flake-parts";
  };

  outputs = inputs@{ self, nixpkgs, flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ "x86_64-linux" "aarch64-darwin" "aarch64-linux" ];

      perSystem = { config, pkgs, system, ... }:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
            overlays = [ ];
          };

          buildInputs = with pkgs; [
            python314
          ];
        in {
          devShells.default = (({ pkgs, ... }:
            pkgs.mkShell {
              buildInputs = buildInputs;
            }) { inherit pkgs; });
        };
    };
}
