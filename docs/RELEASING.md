# Releasing

A release is its own `release/X.Y.Z` branch and pull request. The four
packages carry the same version. The MCP server pins the client and the
common package to it, the service the common package.

1. `uv lock --upgrade --dry-run`. If it moves anything, run
   `uv lock --upgrade` as a commit of its own, then all checks. Check
   the other pins as well: the base images of both Dockerfiles, a newer
   tag or a new digest under the same tag, the actions of the
   workflows, and htmx and Bootstrap Icons in `assets/vendor`, with
   their highest stable version on npm and not the tag `latest`. Each
   update is a commit of its own. The issue "Pinned
   versions have newer releases", which `freshness.yml` keeps daily, lists
   the same, but only as of its last run.
2. Set `version` in the four packages' `pyproject.toml`, the pins
   `benethos-mailbox-client==X.Y.Z` and
   `benethos-mailbox-common[paths,settings]==X.Y.Z` in the MCP server's
   and `benethos-mailbox-common[paths,settings]==X.Y.Z` in the
   service's, then `uv lock` and `uv sync`. Set it as well in
   `.github/publish/mcp-registry/server.json`, there also in the
   bundle's address, in `.github/publish/mcpb/manifest.json` and in
   `containers/production/.env.example`, and regenerate
   `docs/openapi.json`, which carries it. `test_packaging.py` names
   every such place and every version example in the documentation
   that still shows the old one.
3. Close `[Unreleased]` in `CHANGELOG.md` as `[X.Y.Z] - <date>`, in the
   same commit as step 2: `test_packaging.py` holds the version to the
   newest release the changelog names. At its foot, move the link
   `[Unreleased]` to `compare/vX.Y.Z...HEAD` and add the link
   `[X.Y.Z]`.
4. Freeze the migrations new in this release: add `fingerprint(N)` of
   each to `RELEASED` in
   `packages/mailbox-service/tests/data/storage/test_sqlite.py`.
5. After the squash merge: an annotated tag `vX.Y.Z` on `main`, pushed,
   then `gh release create vX.Y.Z --verify-tag --title X.Y.Z` with the
   changelog section as the notes. The published release starts `publish.yml`, which
   uploads the four packages to PyPI and both images to GHCR, attaches
   the Claude Desktop bundle to the release and sends the entry to the
   MCP Registry.
6. Check what shipped: the four packages on PyPI, each image's tags
   `X.Y.Z`, `X.Y` and `latest` on the same revision, the bundle
   `benethos-mailbox-mcp-X.Y.Z.mcpb` and `benethos-mailbox-mcp.mcpb` on
   the GitHub release, and the version in the MCP Registry:
   `https://registry.modelcontextprotocol.io/v0/servers?search=io.github.benethos-hub/benethos-mailbox-mcp`.
