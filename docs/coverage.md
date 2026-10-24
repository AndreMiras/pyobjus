# Cython and PXI line coverage

## Status

The standalone fidelity checks and the Phase 2 native macOS proof passed.
Phase 3 integrates the validated path into the existing `macos-latest`/Python
3.14 matrix entry; this integration still needs its own Actions run and manual
review. Coveralls publication acceptance remains pending. The accepted
post-bootstrap policy is recorded in `tools/coverage/policy.json`.

## Reproducing the spike

Use Python 3.14 in a virtual environment, a working C compiler, and the checkout
root as the working directory:

```sh
python -m pip install -r .ci/coverage-requirements.txt
python -m pip check
python -m tools.coverage.fidelity_spike --output build/coverage-spike
python -m pytest tools/coverage/tests -q
```

Choose a new output directory for each spike run. The command refuses to overwrite
an existing result. Fixture sources are copied into the result's `project/`
directory before compiling; no generated C or extension is written into the
checked-in fixture. Tests build their own isolated copy in pytest's temporary
directory. A compiler selected through standard `CC`, `LDSHARED`, and related
environment variables is supported.

The controlled tracing/test versions are:

| Component | Version |
| --- | --- |
| Python | 3.14; exact patch version recorded per run |
| Cython, both generator and plugin | 3.3.0 |
| coverage.py | 7.17.0 |
| pytest | 9.1.1 |
| pytest-cov | 7.1.0 |

The fixture enables `linetrace=True` and `emit_code_comments=True`, defines
`CYTHON_TRACE=1` and `CYTHON_USE_SYS_MONITORING=0` for C compilation, and selects
coverage's `ctrace` core and the stock `Cython.Coverage` plugin. The monitoring
override is a compiler macro, not a similarly named runtime environment setting.
pytest-cov is disabled during programmatic collection so only one collector owns
the data. Each collection and independent trace recording uses a fresh process;
the cold extension is built but never imported.

## Standalone fixture results — 2026-10-24

Validation ran on Linux x86_64 with CPython 3.14.9, the versions above,
setuptools 84.2.1, wheel 0.48.0, and Zig 0.15.2's Clang 20.1.2 C compiler.
Each spike run retains full environment and compiler details in
`build/coverage-spike/environment.json`. The initial regression command
completed with **12 passed**; the expanded suite is described below.

| Fixture report | Executable lines | Hits | Misses |
| --- | ---: | ---: | ---: |
| Raw import-inclusive, before seeding | 14 | 9 | 5 |
| Raw import-inclusive, after seeding | 23 | 9 | 14 |
| Post-bootstrap, before seeding | 14 | 4 | 10 |
| Post-bootstrap, after seeding | 23 | 4 | 19 |

The raw result is the defective negative control. It is not an eligible
whole-source baseline.

### Attribution findings

- `pxiprobe/bridge.pyx:9` is the body of `never_main()`, which is never called.
  The raw report marks it hit. Independent `sys.settrace` recording identifies
  the event as `{"source": "pxiprobe/bridge.pyx", "line": 9,
  "function": "PyInit_bridge"}` during import. The included `active.pxi` has a
  function definition at line 9; the initializer event retains the main filename.
- In the post-bootstrap candidate, `bridge.pyx:9` is missed.
  `active.pxi:10`, the other uncalled body, and `active.pxi:4`, the untaken return,
  also remain missed.
- The candidate credits `bridge.pyx:6` and `active.pxi:2,3,7`, matching the actual
  `.pyx` → `.pxi` `def` → `.pxi` `cdef` call chain.
- `pxiprobe/__init__.py:1` is hit in the raw control and missed in the candidate,
  as expected when package bootstrap is outside the measurement interval.

No small producer-side correction was selected in this bounded spike. The
reproduced event already has the wrong source/line pair before reporting, so the
candidate uses an explicit measurement interval rather than guessing which
recorded hits to delete. Reliable process-lifetime initialization attribution
has not been demonstrated.

### Denominator and report findings

| Original fixture source | Executable inventory | Candidate hits | Candidate misses |
| --- | ---: | ---: | ---: |
| `pxiprobe/__init__.py` | 1 | 0 | 1 |
| `pxiprobe/bridge.pyx` | 5 | 1 | 4 |
| `pxiprobe/active.pxi` | 8 | 3 | 5 |
| `pxiprobe/inactive.pxi` | 4 | 0 | 4 |
| `pxiprobe/cold.pyx` | 3 | 0 | 3 |
| `pxiprobe/cold_impl.pxi` | 2 | 0 | 2 |
| `pxiprobe/declarations.pxi` | 0 | — | — |
| **Total** | **23** | **4** | **19** |

The three wholly unexecuted compiled sources are absent before seeding. Seeding
adds all nine of their executable lines as misses with the
`Cython.Coverage.Plugin` association. Existing measured hits remain identical;
seeding cannot repair the raw initialization alias.

A second fresh reporting process reproduces the candidate's inventory and
hit/miss sets without changing data. XML source roots and filenames resolve to
the intended built fixture copy. Tests also verify explicit zero-hit fixture
data, rejection of missing collection data, rejection of missing generated C and
recovery after restoration, and failure when a nonempty source cannot be mapped.
The declaration-only include is recorded as intentionally empty, not silently
confused with a discovery failure.

## Selected policy for native validation

**Public label:** “Post-bootstrap Python + Cython line coverage.”

For the native milestone, the selected scope is:

| Property | Definition |
| --- | --- |
| Excluded bootstrap | `import pyobjus`, including its transitive imports, in a fresh process |
| Measurement start | Immediately after bootstrap, before `pytest.main()` and test collection |
| Numerator | Product-source line hits observed after that start in the main pytest process |
| Compiled denominator | Every traceable original-source line in the matching build's generated C |
| Python denominator | Product Python executable lines discovered by coverage.py |
| Initialization-only lines | Retained; missed unless they execute again during the measured interval |
| Build scope | The existing single macOS/Python 3.14 coverage entry; record runner architecture |

The fixture substitutes `import pxiprobe` for the native bootstrap. This is
execution-after-bootstrap coverage over the full traceable-source denominator,
not a function-body-only denominator or complete process-lifetime coverage. It
does not measure inside Objective-C/C helpers or combine other platforms and
architectures. The Guard Malloc subprocess remains a separate functional check.

## Evidence and reusable reporting helper

The ignored `build/coverage-spike/` result contains:

- `result.json`: candidate comparison, inventories, hit/miss sets, independent
  events, and a `policy_approval: pending` marker.
- `environment.json`, `compiler.log`, `build.log`, `source-hashes.json`, and
  `build-hashes.json`: environment, compiler, and source/build provenance.
- `project/`: original source copies, matching generated C, extension binaries,
  separate raw/candidate data, unseeded/seeded XML and manifests, and fresh XML.
- Per-collection and per-report logs, plus `project/trace-events.json`.

`tools/coverage/report.py` contains the reusable inventory and seeding
helper. From a built fixture copy, with repository tooling importable, a fresh
report can be generated with:

```sh
python -m tools.coverage.report --package pxiprobe --data-file .coverage.post-bootstrap-seeded --empty-source pxiprobe/declarations.pxi --output post-bootstrap-recheck.xml
```

Keep matching generated C, its source comments, original sources, configuration,
and data available throughout reporting. Run discovery/reporting from that
project's root; a similarly named file in another checkout must not supply its
source mapping. The adapter checks the pinned Cython version, distinguishes
declared empty sources from failed discovery, and rejects missing input data.
The product runner records the loaded extension path, environment, policy, test
arguments and exit code, and hashes of the original sources/generated C/binary
and configuration. Policy-based reporting rejects failed tests or changed inputs.
It explicitly selects `tools/coverage/coverage.toml`; these plugin settings are
not auto-loaded into ordinary test/build commands. The policy declares the five
expected executable compiled sources and two empty includes. Adding/removing a
source requires an explained policy update; a missing mapping fails reporting.
Cython's synthetic `(tree fragment)` compiler nodes have no original repository
source and are excluded from the original-source inventory.

### Build configuration

`setup.py` uses Cython's supported `Extension` options, `cython_directives` and
`define_macros`, to declare instrumentation. The `PYOBJUS_COVERAGE=1` switch
selects those options when the build backend evaluates the extension definition.
The existing build hook handles platform checks and generated configuration;
it does not mutate tracing settings or force compilation. The proof commands
explicitly request `build_ext --inplace --force` to avoid reusing stale artifacts.

This keeps Cython generation deferred until the build, after platform
configuration is available. A `cythonize()` call at setup-module import time
would require additional restructuring to preserve metadata/sdist behavior.

## Native macOS proof

### Phase 2 Actions result — 2026-10-24

The [native proof job](https://github.com/AndreMiras/pyobjus/actions/runs/40120397600/job/120950476692)
at commit `54e42bb8ee5a21cbea5e1d2ded69c3dc9d27660a` passed on macOS 26.6.2
(arm64), Python 3.14.8, Cython 3.3.0, coverage.py 7.17.0, pytest 9.1.1,
setuptools 84.2.1, and wheel 0.48.0. All enclosing workflow jobs passed too.

- Full suite: **93 passed, 3 skipped, 14 subtests passed**, including the struct
  round-trip and Guard Malloc checks. The separate literals selection passed 7 tests.
- Python + compiled accounting: **1,180 covered, 642 missed, 1,822 executable lines**.
- Compiled inventory: 1,564 lines — `pyobjus.pyx` 541, conversions 463, types 442,
  type encoding 109, debug 9. `common.pxi` and `config.pxi` have empty inventories.
- Literal, dereference, and signature-parser body checks passed. The condition at
  `pyobjus_conversions.pxi:27` is hit in the full run and missed in the literals control.
- Fresh reports reproduced accounting; downloaded source/binary hashes and XML/data
  totals were cross-checked. Missing generated C failed and restoration recovered
  the identical inventory.

That four-file checkpoint used `.ci/cython_coverage_proof.py` and retained
`build/coverage-proof/full/report.json` and `literals/report.json` in the
`cython-coverage-proof-macos-py314-1` artifact. Its separate proof job is now
promoted into the selected matrix entry. The user's request to continue authorizes
Phase 3 implementation; independent human artifact review is not recorded as complete.

### Integrated coverage entry

Only `macos-latest`/Python 3.14 installs the pinned runtime/build stack, performs
the no-isolation editable install and forced instrumented build, and runs the
fidelity regressions before product collection. The fixture tests build isolated
temporary projects with separate data files. The product runner disables
pytest-cov and owns exactly one collector. Ordinary matrix jobs retain isolated
editable installs and their normal functional test path.

Finalization checks all source/build/configuration/policy hashes and the loaded
extension path, seeds missing compiled sources with the Cython tracer, and retains
zero-hit Python modules using coverage.py's Python analysis. Seeding changes only
missing-source accounting, never existing hits. The final XML is generated **after**
seeding; source paths, executable/hit/miss sets, aggregate counts, and native body
anchors must validate before it replaces `coverage.xml`. A second fresh process
checks identical accounting, followed by replay from the snapshot. Coveralls
receives only this final XML, with the existing nonfatal upload-error policy.

The seven-day `coverage-macos-py314-<run-attempt>` artifact retains available
diagnostics even on failure: explicit `.coverage` data, collection metadata,
`coverage.xml`, manifest, policy/configuration, source/build snapshots (including
generated C/comments, configuration, and binary), tool versions, and build/test/report
logs. The manifest separates Python/compiled accounting and names empty inventories
with reasons. Ordinary jobs retain their verbose install/build logs, checked for
absence of the opt-in compilation macros.

The integrated Actions run and its ordinary-build matrix checks have not yet run
for Phase 3. The earlier proof is evidence for the native mechanism, not evidence
that the new integration has passed.

Local Phase 3 validation passes **50 tooling tests**, dependency checks, workflow
linting, an isolated Linux sdist build (without tool-generated bytecode), and the
expected clear unsupported-platform installation failure. The new finalizer also
reprocessed the retained Phase 2 macOS data without native execution: full accounting
remains **1,180 covered / 642 missed / 1,822 executable**, including **1,564 compiled**
and **258 Python** executable lines. Full/literals hit sets, native anchors, and
repeated reporting agree with that artifact. Fresh CI/native acceptance is still required.

### Running the proof

On a clean macOS checkout with Python 3.14, run:

```sh
python -m pip install -r .ci/coverage-requirements.txt
python -m tools.coverage.native_proof --output build/coverage-native
```

Choose a new output directory if it already exists. The native proof:

1. Checks tool versions and dependencies, installs editable without build
   isolation, and forces C generation/native compilation with
   `PYOBJUS_COVERAGE=1`.
2. Builds the native fixture libraries and runs the fidelity tooling tests.
3. Collects the full native suite after bootstrap and generates seeded XML,
   validating literal, dereference, and signature-parser body hits.
4. Regenerates the report in a fresh process and compares source accounting.
5. Runs a separate literals-only collection, checking that `dereference`'s first
   body condition remains missed. That public function has no internal callers
   in the current product sources and is not called by the literals tests.
6. Tests missing-generated-C failure and identical restoration in a disposable
   artifact copy.

Logs, manifests, source/build snapshots, and nonhidden data copies are retained
under the output directory. A successful run writes `acceptance.json`; the
native review gate remains pending until the result is accepted. The literals
control data is not merged into the full-suite baseline.

The underlying commands remain available individually:

```sh
PYOBJUS_COVERAGE=1 python -m pip install --no-build-isolation -e .
PYOBJUS_COVERAGE=1 python setup.py build_ext --inplace --force
make test_lib
python -m pytest tools/coverage/tests -q
python -m tools.coverage.run
python -m tools.coverage.report --output coverage.xml --artifacts build/coverage
python -m tools.coverage.report --output coverage.xml --check-fresh
```

For the isolated native uncalled-body control:

```sh
python -m tools.coverage.run --data-file build/.coverage.literals --metadata build/literals-run.json -- tests/test_literals.py -v
python -m tools.coverage.report --data-file build/.coverage.literals --metadata build/literals-run.json --native-checks literals --output build/literals.xml
```

Keep the same working directory and all matching build/source files until these
reports finish. Generated C, source-position comments, and original sources are
the reporter's executable-line mapping; rebuilding or cleaning before reporting
invalidates that mapping. The finalizer never regenerates C or compiles an extension.

### Replay a retained bundle

Using Python 3.14 with the pinned reporting stack, from a checkout containing
these helpers (or the retained snapshot), run:

```sh
python -m tools.coverage.report --from-artifacts build/coverage --output build/replayed.xml
```

For a downloaded Actions artifact, pass its `build/coverage` directory instead.
Replay verifies every recorded input hash, changes to the snapshot's own root,
and relocates only canonical, recorded coverage-data paths to that root in a new
data file. It never imports the product or loads its native binary, so reporting
does not require Apple frameworks. The replayed executable/hit/miss sets must
match the saved manifest. Its XML resolves to the retained source copy. Original
coverage data and the uploaded XML are preserved.

### Return to an ordinary build

Removing the switch does not change an already compiled binary. After saving any
coverage evidence outside `build/`, clean and rebuild on macOS:

```sh
unset PYOBJUS_COVERAGE
make distclean
python -m pip install -e .
make test_lib
python -m pytest tests -v
```

The unset switch adds no tracing directives/macros or forced-build behavior.
Normal isolated package build requirements remain broad. Updates to the pinned
tracing tools must repeat both fixture fidelity checks and native macOS acceptance.

## Publication and migration record

The preceding pipeline publishes Python-only coverage. The expanded result adds
the matching macOS build's `.pyx`/`.pxi` inventory and excludes bootstrap hits while
retaining initialization-only lines. A lower percentage can reflect this scope
change rather than a test regression. This is one platform/build's traceable
inventory, not a union of macOS/iOS or architecture-specific code. No numeric
coverage threshold is introduced.

The README badge still targets `kivy/pyobjus` on `master`; the native proof ran
in the `AndreMiras/pyobjus` fork and did not publish its candidate report. A fork
upload cannot validate that upstream badge. Phase 4 must record the previous report
identity, first integrated Actions commit/run, manifest totals, intended repository,
Coveralls report URL, and user acceptance after comparing source display and
per-file executable/covered/missed counts. **No trusted published expanded baseline
has been accepted yet.**
