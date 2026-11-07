# zcash_proofs

This library contains the Sprout zk-SNARK circuit and the APIs for creating and
verifying Sprout proofs. The Sapling circuits have moved to the `sapling-crypto`
crate; this crate retains helpers for loading the Sapling proving parameters
from disk but no longer defines those circuits itself.

## License

Licensed under either of

 * Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
   http://www.apache.org/licenses/LICENSE-2.0)
 * MIT license ([LICENSE-MIT](LICENSE-MIT) or http://opensource.org/licenses/MIT)

at your option.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in the work by you, as defined in the Apache-2.0
license, shall be dual licensed as above, without any additional terms or
conditions.


## Parameter downloads in this fork

The `download-params` feature streams parameter files through Ureq with Rustls's
Ring provider and public WebPKI roots. It shares the provider used by the Tor
client and does not install a process-wide provider. The existing optional
per-request timeout and `MINREQ_TIMEOUT` fallback apply to the complete request,
including reading its body. The existing file-length, cryptographic-hash and
returned-error cleanup checks apply to the streamed bytes.

The public download functions return `minreq::Error` from Minreq 3, as in the
Free2Z parameter-download fork. Minreq is retained for this public error type;
it does not provide HTTPS transport. Transport failures are represented as
`minreq::Error::IoError`. Code migrating from upstream's Minreq 2 signatures must
update that error dependency or map the error explicitly at its own boundary.
