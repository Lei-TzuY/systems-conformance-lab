# Unicode normalization interoperability

This domain layer extends the repository's raw-byte Unicode conformance work beyond
UTF-8 decoding and transport segmentation into normalization semantics.

Both targets consume the exact stdin bytes as strict UTF-8. Invalid UTF-8 is converted
to the same canonical JSON rejection before normalization. Valid text is normalized
with one of the four standard forms:

- NFC: canonical composition;
- NFD: canonical decomposition;
- NFKC: compatibility decomposition followed by composition;
- NFKD: compatibility decomposition.

UnicodeNormalizationTarget uses Python's unicodedata.normalize. The Node target uses
Node 22 String.prototype.normalize after fatal WHATWG UTF-8 decoding. Candidate and
oracle remain separate child processes and reuse DifferentialHarness unchanged.

## Executable evidence

The interoperability suite covers stable normalization examples rather than claiming
that two runtimes necessarily ship the same Unicode data version for every assigned
code point. Evidence includes:

- decomposed and composed Latin acute-accent forms under NFC and NFD;
- compatibility normalization of circled digits and the fi ligature under NFKC/NFKD;
- Hangul Jamo composition and syllable decomposition;
- leading UTF-8 BOM preservation;
- strict invalid and truncated UTF-8 rejection before normalization;
- a finite DeterministicByteMutations schedule executed through the real Node/Python
  differential path.

The four normalization forms are explicit target configuration and therefore participate
in replay identity. Unknown or differently-cased form names fail closed at target
construction.

## Scope boundary

This phase does not claim whole-Unicode-version equivalence, case folding, locale-aware
comparison, collation, grapheme segmentation, regex equivalence, identifier security,
or normalization stability for implementation-specific/unassigned code points. It also
does not add normalization policy to the generic harness. Unicode semantics remain in
domain adapters above the stable process, comparison, fuzz, and replay substrate.


## Runtime semantic identity

Normalization results depend on runtime Unicode data rather than argv alone. The
normalization targets therefore bind their semantic runtime identity into process
configuration so the existing replay-context fingerprint can detect version drift.

The Python target captures the Python implementation, exact runtime version, and
`unicodedata.unidata_version`; its worker verifies all three before reading case bytes.
The Node target probes the selected executable through the shared bounded process runner,
captures Node, ICU, and Unicode versions, embeds them in the target script, and verifies
them again before reading case bytes. Probe failure, malformed identity output, and
execution under a different runtime identity fail closed.

This deliberately makes same-context replay conservative across runtime upgrades.
Callers performing an intentional portability experiment may still use the existing
explicit replay-context override, but an upgrade is no longer silently treated as the
same semantic environment.
