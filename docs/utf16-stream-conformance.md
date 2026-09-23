# UTF-16 cross-runtime streaming conformance

This phase extends the raw-byte Unicode domain from UTF-8 into an additional encoding
surface rather than adding more normalization examples. Python and Node execute as
separate child-process targets above the unchanged runner, differential harness,
comparison, replay, and deterministic fuzz layers.

The targets decode explicit UTF-16 little-endian or big-endian byte streams. Byte order
is configuration, not inferred from a BOM. A leading byte-order mark is therefore
preserved as U+FEFF by both targets. Python uses its standard UTF-16LE/BE codecs; Node 22
uses WHATWG TextDecoder with utf-16le or utf-16be labels and ignoreBOM enabled.

## Executable evidence

The cross-runtime suite covers:

- UTF-16LE and UTF-16BE;
- one-shot and incremental decode modes;
- one-, two-, three-, and five-byte chunk widths that split two-byte code units and
  four-byte surrogate pairs at irregular byte boundaries;
- BMP and supplementary-plane text in the same stream;
- explicit BOM preservation under fixed byte order;
- strict rejection of isolated high/low surrogates, high-surrogate-plus-BMP input, and
  odd trailing bytes;
- replacement-mode agreement for the same malformed byte patterns;
- a finite DeterministicByteMutations schedule executed through real Node/Python
  process targets for both byte orders.

Successful text and strict decode rejection use the same bounded semantic JSON shape as
the existing UTF-8 domain. Runtime exception wording and byte offsets are intentionally
not part of the conformance surface.

## Configuration and replay identity

Byte order, mode, error policy, and chunk size are immutable target configuration.
Python carries them in argv; Node embeds them into its immutable script. The normal
CommandTarget/DifferentialHarness replay-context fingerprint therefore distinguishes LE
from BE and one streaming policy from another without adding Unicode policy to the
generic core.

## Scope boundary

This phase claims cross-runtime UTF-16 decoding semantics only for explicit LE/BE byte
order and the shared strict/replace policies exercised by the suite. It does not claim
BOM-driven endian auto-detection, UTF-32, CESU-8, WTF-8, surrogatepass behavior,
grapheme segmentation, collation, or locale services. Those remain separate
architectural surfaces.
