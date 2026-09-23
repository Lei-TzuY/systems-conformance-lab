# Conformance substrate stability checkpoint

This document records the bounded architecture checkpoint for `systems-conformance-lab` after the deterministic fault controller and differential-harness integration work.

The goal of this checkpoint is not feature completeness. It is to make the reusable correctness substrate explicit enough that downstream systems repositories can depend on stable responsibilities without pulling product-specific semantics into the core package.

## Stable responsibility layers

| Layer | Current responsibility | Intentionally outside this layer |
| --- | --- | --- |
| `runner` | safe argv execution, stdin bytes, timeout/process-tree cleanup, bounded stream capture, structured execution records | target protocol semantics, output normalization |
| `comparator` | deterministic observable-result comparison and product-vs-infrastructure classification | domain-aware equivalence rules |
| `failure` | stable failure-class identity excluding volatile diagnostics | root-cause inference |
| `fuzz` | deterministic bounded case scheduling and first-failure capture | generators, mutators, corpus policy, coverage guidance |
| `reducer` | deterministic first-improvement loop with explicit progress/budget | domain-specific shrink candidates and measures |
| `repro` / `retention` | deterministic evidence bundles and safe bounded retention | artifact upload/storage services |
| `fault` | deterministic logical-operation trigger intent | kill/corrupt/drop/delay side effects and target-specific failure mapping |
| `harness` | immutable command-target snapshots; candidate/oracle execution; comparison; failure-signature preservation; repro publication | case generation, mutation, concrete fault behavior, target lifecycle orchestration |

## Integrated real-target path

The repository now exercises one complete real-process path rather than validating every primitive only in isolation:

1. deterministic input bytes are selected by `run_fuzz_campaign`;
2. `DifferentialHarness.compare` executes candidate and oracle `CommandTarget` processes through `run_process`;
3. `compare_results` classifies the pair;
4. `failure_signature` captures stable mismatch identity;
5. `reduce_case` calls `DifferentialHarness.preserves_failure` while deleting input bytes;
6. `DifferentialHarness.write_repro` re-evaluates the minimized input and rejects optional signature drift;
7. `write_repro_bundle` persists the exact minimized bytes plus structured candidate/oracle/comparison/signature records.

The end-to-end regression uses actual child processes and therefore covers the integration contract between process execution, result classification, reduction identity, and reproducer publication.

## Invariants at this checkpoint

The following are treated as cross-module invariants rather than individual implementation details:

- shell execution is never required for command targets;
- caller-owned argv/env containers cannot mutate an already-created `CommandTarget`;
- infrastructure failures are never silently downgraded into product mismatches;
- matching comparisons never carry a failure signature;
- reducer preservation compares stable failure signatures rather than output text or exception messages;
- repro publication requires a currently failing input;
- optional expected-signature checking prevents a reducer or later rerun from publishing a different failure class under the original identity;
- fuzz and reduction budgets remain explicit and deterministic;
- concrete fault side effects remain outside `FaultController` and `DifferentialHarness`;
- target-specific normalization, generation, mutation, and lifecycle rules remain adapter responsibilities.

## Integration review conclusions

The existing primitives are sufficiently separated to remain independently reusable. The missing architectural piece was not another fuzzing or fault feature; it was a narrow composition boundary proving that the primitives work together against real process targets.

`DifferentialHarness` is therefore deliberately small. It does not become a scheduler, corpus manager, mutation engine, fault backend, or product plugin registry. Downstream repositories should build thin adapters around this boundary and keep their own semantic knowledge local.

## Deferred architecture phases

The following are not part of the current checkpoint and should not be added merely to create activity:

- coverage-guided or evolutionary fuzzing;
- protocol/filesystem/compiler-specific generators in the core package;
- symbolic/concolic execution;
- distributed worker scheduling;
- process-kill, disk-corruption, packet-loss, clock, or syscall fault backends in the generic controller;
- a universal target plugin registry;
- remote artifact storage or dashboard services;
- broad normalization/equivalence policies that encode one product domain.

A future change in one of these areas should be justified by a concrete downstream integration and should preserve the current product-vs-infrastructure distinction and reproducibility guarantees.

## Maintenance mode

After this checkpoint, routine work should follow a patrol model:

- fix reproducible correctness bugs;
- fix CI/toolchain regressions;
- tighten an invariant when a downstream integration exposes an ambiguity;
- add a reusable primitive only when at least one real target needs it;
- avoid speculative feature expansion when the existing substrate already expresses the required test.

In short: keep the correctness core boring, deterministic, and reusable. Product complexity belongs above it.


## Domain-adapter phase promotion

The generic correctness substrate remains at the stable boundary above. The next active
architecture phase is target-specific composition above that core, beginning with a
bounded two-connection SQLite scenario executor.

This promotion addresses an observed integration pattern: reader and writer semantics
were increasingly represented by one fixed worker per scenario. The new adapter keeps
the core harness unchanged while moving reusable connection ordering into a strict,
budgeted data-plane program. Its first acceptance evidence covers WAL snapshot visibility
and writer exclusion across DELETE and WAL journal modes with real process and database
execution.

Specialized crash, backup, checkpoint, and multi-process workers are not deprecated by
this promotion. They remain authoritative where the two-connection program cannot
express the same failure boundary without weakening evidence.


### Two-connection consolidation checkpoint

The bounded scenario executor now owns recognized SQLite busy outcomes for begin,
non-query, and query operations. This makes stale-reader SQLITE_BUSY_SNAPSHOT and
DELETE-vs-WAL reader contention executable through the same strict data-plane protocol.

The former fixed WAL snapshot, WAL busy-snapshot, and reader-contention workers are
retired after equivalent real-process regressions moved onto the generic executor.
This is an architecture consolidation, not a reduction in evidence: the semantic
assertions remain executable while duplicate temporary-database and connection
orchestration is removed.

Crash recovery, online backup, checkpoint, reader-process, writer-process, and
durability targets remain specialized because their process or failure boundaries are
outside the two-connection executor's contract.


### Two-connection structured triage checkpoint

After consolidating simple reader/writer scenarios into the bounded executor, the next
architecture layer is failure minimization rather than additional fixed workers. The
two-connection adapter now mirrors the mature query/transaction path with deterministic
step deletion, setup deletion, scalar parameter simplification, stable-signature
preservation, bounded reducer work, repro publication, and replay.

The generic reducer and harness remain unchanged. SQLite request shape and concurrency
semantics stay in target-specific modules above the stable core. Real DELETE-vs-WAL
reader-contention evidence proves the vertical path from process execution through
structured reduction to minimized reproducible evidence.


### Two-connection discovery checkpoint

The two-connection SQLite adapter has now progressed from executable scenarios and
structured triage to bounded discovery. Valid scenario seeds can be mutated
deterministically across begin-mode and scalar-parameter dimensions, while a
target-specific feedback evaluator extracts only finite transcript structure.

A real DELETE-vs-WAL campaign proves discovery rather than fixture enumeration: an
IMMEDIATE seed matches, the deterministic EXCLUSIVE mutation exposes the journal-mode
reader-contention difference, and the feedback campaign retains that product mismatch.
The generic fuzz scheduler, feedback corpus policy, differential harness, and reducer
remain unchanged; SQLite concurrency semantics stay above the stable core.

Mutation generation is itself structurally bounded before campaign execution: seed
decode count and candidate-construction visits have independent ceilings, candidate
visits are claimed before materializing the next JSON case, and exhaustion fails closed
with deterministic work evidence. This prevents a large valid scenario from expanding
into unbounded adapter-side work before the generic evaluation budget can apply.


### Two-connection discovery-to-repro checkpoint

The adapter now closes the composition gap between bounded discovery and structured
triage. A target-specific orchestration function runs deterministic feedback-guided
scenario exploration, selects the first retained stable failure, reduces that exact
witness through the established step/setup/parameter phases, publishes a repro under the
captured signature, and leaves replay validation to the existing harness contract.

This is executable cross-layer integration rather than another fixed scenario worker.
A real matching `IMMEDIATE` seed is mutated to the `EXCLUSIVE` DELETE-vs-WAL
reader-contention difference, the campaign-retained witness is minimized, and the
resulting context-bound repro replays with the same stable failure identity. Campaign,
mutation-construction, and reducer work remain independently bounded; no-failure
campaigns fail closed without publishing evidence.


### Two-connection portable archive evidence checkpoint

The two-connection adapter now carries discovered failure evidence across the portable
archive boundary. A real feedback-guided DELETE-vs-WAL mismatch is minimized, exported
through the validated deterministic archive format, imported into a private snapshot for
replay, checked against the original replay context and stable failure signature, and
returned with the SHA-256 of the exact archive bytes that were executed.

A copied archive can be replayed at a different path while pinning that digest, proving
that the evidence identity survives transport independently of path naming. Existing
archive validation and replay primitives remain authoritative; this checkpoint adds only
target-specific composition above them. No-failure discovery and pre-existing archive
destinations fail closed before publishing new transport evidence.


### Second conformance domain: UTF-8 streaming checkpoint

The repository has promoted beyond a single SQLite-centered executable domain.
UTF8DecodeTarget introduces a raw-byte streaming codec boundary above the unchanged
generic process/differential substrate. One-shot and incremental UTF-8 decoding are
compared through real child processes across multibyte chunk boundaries, invalid and
truncated input, and strict/replace/ignore policies.

A finite deterministic byte-mutation campaign is also exhausted against this second
domain and must produce no differential failure. This proves that the shared byte-input,
process execution, comparison, and fuzz scheduling layers are reusable without a JSON
request protocol or SQLite lifecycle. The checkpoint intentionally stops short of
cross-runtime Unicode claims; broader codec interoperability is a later architectural
phase.


### UTF-8 cross-runtime interoperability checkpoint

The second conformance domain now crosses a real runtime boundary. A Node 22 WHATWG
TextDecoder target emits the same bounded semantic JSON surface as the Python UTF-8
target, while the generic runner, differential harness, comparator, and fuzz scheduler
remain unchanged.

Executable evidence covers one-shot and incremental decoding, multibyte chunk
boundaries, BOM preservation, strict rejection, selected replacement semantics, and a
finite deterministic strict-mode mutation schedule. CI provisions Node explicitly on
Ubuntu, Windows, and macOS for both supported Python versions, so the interoperability
claim is exercised rather than skipped.

The cross-runtime claim is deliberately limited to shared UTF-8 strict/replace
semantics. Python's ignore mode and broader Unicode/ICU services are not generalized by
this checkpoint.


### UTF-8 irregular segmentation checkpoint

Cross-runtime UTF-8 interoperability now covers a transport segmentation policy that is
independent of a single fixed chunk width. Python and Node targets accept the same
bounded cyclic chunk pattern while preserving raw stdin bytes and the existing semantic
JSON comparison surface.

Executable evidence crosses uneven boundaries through valid multibyte sequences, BOM,
malformed and truncated input, and strict/replace policies. Pattern configuration is
bounded to 64 positive widths and participates in replay identity. Legacy fixed-size
targets retain their previous argv when no pattern is configured, so the new capability
extends rather than replaces the established evidence surface.


### Unicode normalization interoperability checkpoint

The second conformance domain has promoted from byte decoding and transport segmentation
into a distinct Unicode semantic service. Python unicodedata.normalize and Node 22
String.prototype.normalize now execute as separate real-process targets above the
unchanged differential substrate.

Executable evidence covers NFC, NFD, NFKC, and NFKD using stable canonical and
compatibility vectors, Hangul composition/decomposition, BOM preservation, strict
invalid UTF-8 rejection, and a finite deterministic byte-mutation campaign. The
normalization form is bound into target configuration and replay identity.

This checkpoint deliberately avoids a blanket claim that Python and Node expose the
same Unicode data version for every code point. It does not generalize case folding,
locale/collation, grapheme segmentation, identifier security, or additional encodings.
Those remain separate architectural surfaces.


### Unicode normalization runtime-identity checkpoint

Normalization evidence now binds the semantic runtime tables that can change behavior
without changing a target's logical form. Python captures implementation/runtime and
`unicodedata` Unicode versions; Node captures Node, ICU, and Unicode versions through
the shared bounded runner. Both workers verify the captured identity before consuming
case bytes, and the identity is embedded in target argv/script so the unchanged harness
naturally includes it in replay-context SHA-256.

This closes a reproducibility gap left by the initial normalization interoperability
slice: a runtime Unicode-table upgrade can no longer be mistaken for the same replay
context merely because argv, cwd, environment, and execution ceilings are unchanged.
The generic repro schema and harness remain untouched.


### UTF-16 cross-runtime streaming checkpoint

The Unicode domain now spans a second wire encoding rather than only adding semantic
vectors inside UTF-8 or normalization. Python and Node decode explicit UTF-16LE/BE raw
stdin through separate child processes while the generic execution/comparison/fuzz
substrate remains unchanged.

Executable evidence crosses byte-order, one-shot/incremental execution, chunk widths
that split code units and surrogate pairs, BOM preservation, strict malformed/truncated
surrogate rejection, replacement semantics, and finite deterministic byte mutation.
Byte order and streaming policy remain target configuration and therefore participate in
replay identity.

This checkpoint deliberately stops at explicit UTF-16LE/BE decoding. BOM-driven endian
selection, UTF-32, grapheme segmentation, collation, and locale services remain distinct
future interoperability surfaces.


### HTTP URL parser interoperability checkpoint

The repository now exercises a third semantic domain: structured URL parsing. Python
urllib.parse and Node 22 WHATWG URL execute as separate real-process targets above the
unchanged runner, differential comparison, discovery, repro, and replay substrate.

Executable evidence proves a shared absolute HTTP/HTTPS subset and also preserves native
parser behavior strongly enough to surface stable policy differences: WHATWG dot-segment
removal, default-port elision, and special-URL backslash handling differ from
urllib.parse. A deterministic discovery schedule captures one such product mismatch,
publishes the exact witness as a context-bound repro, and replay preserves its stable
failure identity.

Python implementation/version and Node process.version are bound and verified before
stdin consumption so parser-runtime upgrades change replay identity instead of silently
reusing the same context. This checkpoint deliberately does not generalize all WHATWG
URL behavior, IDNA/UTS #46, relative-base resolution, file URLs, or browser security
semantics.


### HTTP relative-resolution interoperability checkpoint

The URL domain now moves beyond parsing one absolute input into a two-input resolution
boundary. Python urllib.parse.urljoin/urlsplit and Node WHATWG URL consume the same
binary-framed base/reference request through separate real processes while the generic
runner, comparison, discovery, repro, and replay layers remain unchanged.

Executable evidence covers parent/same-directory, query-only, fragment-only,
network-path, and absolute references. The adapters also preserve native divergence
instead of normalizing it away: WHATWG special-URL backslash handling and empty-reference
fragment behavior surface as stable product mismatches. A deterministic discovery
schedule publishes and replays a real backslash-resolution witness.

The request protocol itself is bounded by the harness input ceiling and uses a four-byte
base-length frame so resolution evidence is not confounded by JSON parser differences.
Python and Node runtime versions remain verified replay identity. IDNA/UTS #46, file and
opaque URLs, browser origin policy, form encoding, and percent-encoding normalization
remain separate future surfaces.


### IDNA hostname interoperability checkpoint

The URL domain now includes Unicode hostname-to-ASCII processing as an independent
standards/policy surface. Python stdlib IDNA2003/Nameprep and Node WHATWG
domain-to-ASCII execute as separate child processes while the generic runner,
differential comparison, failure discovery, repro, and replay substrate remains
unchanged.

Executable evidence proves a shared lowercase/Unicode subset and preserves real policy
differences instead of normalizing them away: sharp-s mapping, ZERO WIDTH JOINER
handling, and ASCII hostname case surface as stable product mismatches. A deterministic
discovery witness is published and replayed under the original stable failure signature.

Replay identity is strengthened for the semantic tables that govern the domain. Python
binds implementation/version and its Unicode 3.2 Nameprep table identity; Node binds
Node, ICU, and Unicode versions and verifies them before processing input. DNS resolver
behavior, certificate matching, public-suffix policy, and browser origin/security rules
remain outside this checkpoint.


### form-urlencoded interoperability checkpoint

The URL domain now crosses into ordered key-value serialization/parsing rather than only
URL structure. Python urllib.parse and Node WHATWG URLSearchParams execute through
separate real child processes above the unchanged generic execution, comparison,
discovery, repro, and replay substrate.

Encode requests use a binary ordered-pair frame so duplicate keys and ordering are
preserved without confounding JSON parser behavior. Decode requests consume raw form
body bytes, with strict UTF-8 transport validation kept separate from percent-decoded
UTF-8 policy.

Executable shared evidence covers plus/space handling, literal plus, UTF-8 percent
encoding, duplicate keys, empty fields, malformed percent triplets, and blank values.
Stable native differences remain evidence rather than being normalized away: tilde and
asterisk serialization differ between Python quote_plus/urlencode and WHATWG
URLSearchParams, while invalid percent-decoded UTF-8 is strict-rejected by Python and
replacement-decoded by Node. Deterministic discovery publishes and replays both encode
and decode witnesses.

Mode and runtime versions remain target configuration and replay identity. Browser
FormData/multipart behavior, URLSearchParams mutation/sort APIs, non-UTF-8 form
encodings, and browser navigation/form-submission policy remain outside this checkpoint.


### Full-URL query canonicalization checkpoint

The URL domain now composes parser and form-codec semantics in one real-process pipeline
rather than testing those boundaries only in isolation. Python urllib.parse and Node
WHATWG URL/URLSearchParams parse one absolute HTTP(S) URL, decode its query to ordered
pairs, re-encode through native form policy, write the canonical query back into the URL,
and serialize the complete result.

Executable shared evidence covers space-to-plus canonicalization, duplicate ordering,
blank fields, literal malformed percent triplets, raw Unicode query values, plus
semantics, and empty-query removal. Native differences remain visible: tilde/asterisk
encoding policy and invalid percent-decoded UTF-8 each produce stable product mismatches
that deterministic discovery publishes and replay reproduces.

Cases are restricted to the existing shared HTTP(S) parser subset so known host/path/port
parser differences are not misattributed to query policy. Python and Node runtime
identity remain verified replay context. Full URLSearchParams mutation/sort APIs, file
and opaque URLs, browser origin/security, multipart forms, non-UTF-8 form encodings, and
navigation behavior remain outside this checkpoint.


### Stateful URLSearchParams interoperability checkpoint

The URL domain now includes ordered query-state mutation rather than only stateless form
codec operations or full-URL query round trips. A bounded binary protocol carries an
initial duplicate-preserving pair list plus append/set/delete/sort operations to separate
Python and Node child-process targets.

Executable evidence covers duplicate-key position semantics, missing-key append,
delete-all behavior, stable ASCII sort, and post-mutation serialization. The adapters
also preserve a genuine native policy difference: WHATWG URLSearchParams.sort compares
UTF-16 code units, while Python native string sort compares Unicode code points.
Supplementary-plane versus BMP-private-use names therefore provide a stable product
mismatch that deterministic discovery publishes and replay reproduces.

Initial-pair, operation, and field-byte ceilings plus runtime identity remain immutable
target configuration and replay context. The generic runner, comparator, discovery,
repro, and replay layers remain unchanged. Browser-live URL coupling, iterator mutation,
non-UTF-8 forms, multipart submission, and broader navigation/security policy remain
outside this checkpoint.


### Live URL/searchParams coupling checkpoint

The URL phase now composes URL structure and stateful query mutation through a live
cross-layer boundary. One bounded binary request carries an absolute HTTP(S) URL plus
append/set/delete/sort and direct-search-replacement operations. Separate real-process
targets then emit a state snapshot after every operation, including the serialized URL,
the URL search string, ordered parameter pairs, and native form serialization.

The Node target uses one WHATWG `URL` object and retains its original live
`url.searchParams` view for the entire program. This makes both synchronization
directions executable: mutating the params object immediately rewrites the URL query,
while assigning `url.search` immediately refreshes that already-referenced params view.
The Python target is deliberately documented as a composed model, not as a claim that
the Python standard library exposes a native WHATWG live object: it combines
`urllib.parse` URL state, duplicate-preserving ordered pairs, and native form encoding.

Executable evidence covers duplicate semantics across URL updates, raw `%20` search
replacement without premature URL canonicalization, later params mutation that
canonicalizes the full query, stable sorting, deletion, and fragment preservation.
Native form-encoding policy is not normalized away: a tilde/asterisk append propagates
the existing Python-vs-WHATWG serialization difference into `search` and the complete
`href`, and deterministic discovery publishes and replays that cross-layer witness.

URL-byte, operation-count, and field-byte ceilings plus Python/Node runtime identity are
immutable target configuration and replay context. The generic runner, comparator,
discovery, repro, and replay layers remain unchanged. Cases stay within the established
shared HTTP(S) parser subset so parser-policy differences are not misattributed to live
coupling. Iterator mutation during traversal, two-argument delete/has extensions,
file/opaque URLs, browser origin/security state, navigation/submission, multipart forms,
and non-UTF-8 form encodings remain outside this checkpoint.


### Base64/Base64url codec interoperability checkpoint

The conformance surface now includes binary-to-text codec behavior through separate
Python stdlib and Node Buffer child-process targets. Encode mode consumes arbitrary bytes;
decode mode requires ASCII transport and emits decoded bytes as lowercase hexadecimal,
keeping transport validation separate from codec policy.

Executable shared evidence covers canonical Base64, complete unpadded quartets, arbitrary
binary bytes, shared forgiving-decode cases, and Base64url alphabet handling. Native
policy differences remain visible rather than normalized: Node accepts missing padding
and several flexible spellings that Python rejects, while Node Base64url encoding omits
padding that Python urlsafe_b64encode retains. Deterministic discovery publishes and
replays a missing-padding mismatch under the existing stable failure identity.

Mode, alphabet, Python implementation/version, and Node version remain immutable replay
configuration. The generic runner, comparator, discovery, repro, and replay layers are
unchanged. MIME/PEM wrapping, streaming transforms, browser atob/btoa DOMString policy,
data URLs, and cryptographic integrity/canonical-signature rules remain separate future
surfaces.

