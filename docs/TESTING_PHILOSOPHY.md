# Testing Philosophy

`lpt2d` should prefer tests that run the same production paths real users rely
on. That is the right default for a renderer, a strict authored JSON format, and
an engine where physical behavior matters more than internal call structure.

This project is not pure business logic, though. It mixes a C++ renderer, Python
authoring APIs, JSON interchange, CLI tooling, GUI code, and performance
evaluation. The philosophy needs to be strong enough to guide design without
pretending every test should be the same kind of test.


## Core stance

- Default to real production code paths.
- Mock only at true boundaries, and do it reluctantly.
- If testing logic requires heavy mocking, extract the logic instead.
- Separate correctness tests from performance and benchmark checks.


## What "real code path" means here

For this repo, the highest-value tests usually do one or more of these:

- parse real shot JSON through the C++ loader
- construct real `Scene`, `Shot`, `Look`, and `TraceDefaults` objects
- render through the real `_lpt2d.RenderSession` when renderer behavior is under test
- assert on observable outcomes: validation failures, serialized JSON, pixels,
  derived image metrics, written files, or CLI outputs

These tests matter because they catch integration mistakes between Python, C++,
and authored data. A mock-heavy test can look precise while skipping the exact
code that tends to break in this project.


## Valid boundaries for fakes and test doubles

Mocks are not forbidden. They are a boundary tool.

Reasonable boundaries in `lpt2d` include:

- GPU, OpenGL, windowing, and display concerns
- subprocess, build, and git integration in evaluation tooling
- filesystem layout when a temp directory expresses the contract better than
  mutable repo state
- wall clock and randomness when determinism is required
- future external services, if the project gains any

Prefer small, purpose-built fakes, temp directories, or controlled inputs over
generic dynamic mocks. A fake or fixture should model a boundary contract, not
replace half the system.


## What should usually run for real

These are usually not good candidates for mocking:

- scene validation rules
- JSON serialization and deserialization
- renderer session behavior
- image and stats comparison logic once data already exists
- Python builders, mutation helpers, and typed value objects

If those tests are hard to write without patching internals, that is usually a
signal that the production code boundary is in the wrong place.


## Determinism, tolerance, and stochastic rendering

The renderer is stochastic. The test strategy has to acknowledge that directly.

- Use deterministic seed modes for correctness tests whenever possible.
- Use tolerances for pixel or metric comparisons when exact equality is not a
  realistic contract.
- Prefer assertions on physically meaningful behavior, image metrics, or stable
  derived values over brittle byte-for-byte image equality.
- Keep benchmark expectations out of most correctness tests. Performance drift
  belongs in evaluation and benchmark workflows, not in the fast edit loop.

A flaky render test is not "high fidelity." It is an unclear contract.


## Not every test should render

Rendering is expensive. When the behavior under test is pure or mostly pure
logic, extracting that logic is better than hiding it under a render call just
to make the test sound more integrated.

Good candidates for direct logic tests include:

- look and exposure selection from `FrameStats`
- baseline comparison verdict logic
- histogram and quality summaries
- scene and shape builders
- path and authored-shot helper logic

The goal is not "always start at the outermost entry point." The goal is to use
the outermost entry point that meaningfully exercises the behavior under test.


## Long setup is a smell, but not an absolute rule

Long setup often signals unnecessary coupling. That is useful pressure. But in
this repo, some tests are naturally richer because the domain is richer.

Examples:

- Building a realistic scene for a geometry or lighting invariant is often the
  test.
- Preparing a baseline directory in a temp tree may be the clearest way to test
  evaluation I/O.
- Constructing authored JSON with strict required fields is not accidental
  boilerplate if the contract itself is strict.

Treat long setup as a design question, not an automatic design failure. The
right question is: "Does this setup express the contract, or does it only exist
to work around an awkward implementation?"


## Recommended test layers for this repo

Different layers answer different questions:

- C++ unit tests: fast checks for geometry, scene validation, serialization,
  color, and spectrum logic
- Python unit tests: fast checks for builders, stats, comparison logic, and
  extracted analysis helpers
- Python integration tests: JSON roundtrips, validation behavior, save/load
  flows, and other cross-language contracts
- Render integration tests: physically meaningful image-space or metric-space
  assertions through the real renderer
- System tests: CLI workflows, canonical examples, and end-to-end artifact
  generation
- Evaluation and benchmarks: render-speed and fidelity tracking, kept separate
  from ordinary correctness gates

The philosophy is not "everything becomes an integration test." It is "pick the
smallest test that still exercises the real contract."


## Design feedback from tests

Tests are a design signal in this project.

Watch for these patterns:

- repeated monkeypatching to reach logic that could be a function
- tests that only assert on calls instead of visible outcomes
- render tests that exist only because logic was not extracted
- failures that arrive only as noisy pixel diffs when a lower-level invariant
  could have been checked directly

The first response should usually be to improve the code boundary or add a
lower-level test layer, not to write a more clever mock.


## Summary

`lpt2d` should favor real code paths, real renderer behavior, and real authored
data contracts. It should also be explicit about stochastic rendering,
tolerance-based assertions, and the difference between correctness tests and
benchmark workflows.

If a mock removes the behavior you actually care about, it is the wrong test.
If a real render is hiding logic that should be isolated, it is also the wrong
test.
