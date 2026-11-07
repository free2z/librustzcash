# Reviewed dependency source bridges

Free2Z maintainers own the transient forks listed in `owned-sources.json`.
Each entry names one exact repository revision, its complete tracked file
inventory and SHA256 hashes, the independent review, and the upstream change
that retires the bridge. An entry does not approve another revision or the
package published under the same version on crates.io.

The required **Vet Rust dependencies** job runs the source checker and its
negative controls before Cargo Vet. The checker compares the locked and resolved
package identities, rejects duplicate registry copies, verifies the actual Git
revision and tree, and hashes every tracked file. Unexpected files, including
ignored build scripts and Cargo configuration, fail verification. Cargo's
generated `.cargo-ok` and dependency-local `Cargo.lock` are permitted; the
workspace lock controls resolution. This is a source identity check in a
reviewed CI checkout, not protection against concurrent hostile filesystem
mutation after validation.

The listed forks have `audit-as-crates-io = false` because they are maintained
and reviewed as exact owned source. The checker requires a one-to-one match
between that policy and the ownership inventory. Other Git dependencies must
retain registry audit enforcement. Every transitive third-party dependency
continues through Cargo Vet. There are no wildcard ownership entries, new
exemptions, or certificates for the corresponding registry packages.

## utf8-zero

The bridge uses `free2z/utf8-zero` revision
`c6fdaade595b9f8a8a8c24d7ab152213532b8fd8`, tree
`c86aae0c1d0164774c06c2488e3c105d453881f0`.
Its three production modules and package manifests received a complete source
review. The checked buffered-slice change and surrounding recovery logic
received an additional independent review in
[fork PR1](https://github.com/free2z/utf8-zero/pull/1).

Five upstream tests, five doctests, a no-default-features build, and additional
private reader regressions passed against identical production source. The
fork's lint, test, no_std and Miri jobs passed on that reviewed source. The
private regressions are not included in public CI. Throughput impact of the
additional validation pass has not been measured.

Retire this entry when
[upstream PR2](https://github.com/algesten/utf8-zero/pull/2) or an equivalent
reviewed change is available upstream and the consuming graph passes its source
and behavior checks. Remove the Git patch, ownership entry and policy together;
qualify the actual replacement registry version independently.
