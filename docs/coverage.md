# Cython and PXI line coverage

## Status

The standalone fidelity checks, Phase 2 native macOS proof, and Phase 3 integrated
Actions run passed. All 11 jobs in the integrated workflow succeeded; independent
artifact replay reproduces the native accounting. Phase 3 manual integration
review was subsequently delegated to the agent and passed. The user accepted
Phase 3. Coveralls' stored line accounting matches the artifact, but publication
acceptance awaits the upload-path correction and intended upstream result. The accepted
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

Local Phase 3 validation passes **50 tooling tests**, dependency checks, workflow
linting, an isolated Linux sdist build (without tool-generated bytecode), and the
expected clear unsupported-platform installation failure. The new finalizer also
reprocessed the retained Phase 2 macOS data without native execution: full accounting
remains **1,180 covered / 642 missed / 1,822 executable**, including **1,564 compiled**
and **258 Python** executable lines. Full/literals hit sets, native anchors, and
repeated reporting agree with that artifact. The integrated run below now provides
fresh CI/native evidence. The delegated technical review below also passes;
the user has accepted the integrated result.

### Phase 3 Actions result — 2026-10-24

[Python package run 40124899719](https://github.com/AndreMiras/pyobjus/actions/runs/40124899719)
for commit `e3dcfbaf067f3f60d42270c5ce4490a048c9e31a` passed **all 11 jobs**:
the selected coverage entry, nine ordinary macOS entries, and Ubuntu's
unsupported-platform/sdist check. Step conclusions confirm that only the existing
`macos-latest`/Python 3.14 entry runs the new coverage pipeline.

The [selected job](https://github.com/AndreMiras/pyobjus/actions/runs/40124899719/job/120964120466)
ran on macOS 26.6.2 with arm64 execution and Python **3.14.8**, using the pinned
tracing/test stack, setuptools **84.2.1**, and wheel **0.48.0**. Its forced build
regenerated source-comment-bearing C and compiled universal2 with both required
macros. The native tooling suite passed **50 tests in 14.84s**. The product suite
passed **93 tests, with 3 skips and 14 passing subtests in 2.42s**, including Guard
Malloc and the struct round-trip regressions. The isolated literals selection
passed **7 tests** and retained the expected uncalled `dereference` body miss.

| Source group | Covered | Missed | Executable |
| --- | ---: | ---: | ---: |
| Python | 122 | 136 | 258 |
| Compiled `.pyx`/`.pxi` | 1,058 | 506 | 1,564 |
| **Total** | **1,180** | **642** | **1,822** |

All five executable compiled inventories and both empty declarations/configuration
inventories are present. The full run has no wholly zero-hit compiled file; the
native fixture regressions independently verify that case. Source/binary hashes,
XML path composition, per-file hit/miss sets, stored data, manifests, and fresh CI
reporting/replay were independently cross-checked in the downloaded artifact.
Linux replay without loading the macOS extension reproduces the same accounting,
including a repeated `--check-fresh` pass. A missing-generated-C negative control
in a disposable source snapshot fails, and restoration recovers the same inventory.

The [coverage artifact](https://github.com/AndreMiras/pyobjus/actions/runs/40124899719/artifacts/12572384515)
is `coverage-macos-py314-1`, **2,970,530 compressed bytes**, retained until
**2026-10-31**. Its primary evidence is `build/coverage/manifest.json`, the final
root `coverage.xml`, `build/coverage/pytest.log`, and `build/coverage/sources/`.
The job took **97s**, including **48s** for instrumented install/build and **1s**
for finalization/fresh reporting/replay according to Actions step timestamps.

All ordinary build-control checks passed. As a representative independent check,
the [ordinary macOS/Python 3.13 job](https://github.com/AndreMiras/pyobjus/actions/runs/40124899719/job/120964120573)
retained a native compilation command without either opt-in macro and passed
**93 tests, with 3 skips and 14 passing subtests**.

The uploader consumed the validated final XML and received
[Coveralls job 190211394](https://coveralls.io/jobs/190211394). This confirms the
upload handoff for the fork run. Phase 4 verified the stored line accounting and
identified a filename-prefix correction, documented below. Rendered source display
and publication to the intended upstream badge target remain open.

### Delegated integration review — 2026-10-24

At the user's request, the agent also performed the source-level, workflow-scope,
and documentation reviews. **All passed; no integration defect was found.**

- Downloaded the exact artifact ZIP by ID and matched its SHA-256 against GitHub's
  artifact metadata. All **110 files** match the extracted bundle, and **65
  tracked-source copies** match commit `e3dcfba`.
- Checked original source statements against both raw data and manifest entries.
  The literal return bodies at `pyobjus_types.pxi:374,382` are hit in both runs.
  `pyobjus_conversions.pxi:27` is hit in the full suite, and all **35 traceable
  `dereference` body lines** are missed in the literals-only control, which has no
  caller of that function. The parser body at `type_enc.pxi:11` is hit in the full
  suite and missed in the literals control, consistent with the tests' calls.
- Checked the bootstrap boundary directly: package initialization, main-source
  initialization at `pyobjus.pyx:71`, and debug configuration at `debug.pxi:1`
  remain missed. Called function bodies receive correctly attributed hits while
  their initialization-only definition lines remain missed.
- Confirmed the report contains the five executable compiled sources and six
  product Python modules once each, with no generated C, binaries, or fixtures
  counted as product entries. Declaration/configuration-only includes legitimately
  have empty inventories.
- Reviewed actual compiler commands from **all nine ordinary-build artifacts**:
  none enables either opt-in macro. Workflow definitions and actual step outcomes
  agree that only macOS/Python 3.14 owns the coverage pipeline.
- Matched the README and this document to the accepted policy: post-bootstrap
  main-process line coverage, full retained denominator, scoped platform/build,
  functional-only subprocess check, required artifact lifetime, and clean rebuild
  procedure. The upstream badge identity remains explicitly distinguished from
  the fork's successful upload.

The user accepted Phase 3 after receiving these delegated review results and
authorized publication validation. This records acceptance of agent-performed
review, not independent human inspection of the artifacts.

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

The previous pipeline published Python-only coverage. The expanded result adds
the matching macOS build's `.pyx`/`.pxi` inventory and excludes bootstrap hits while
retaining initialization-only lines. A lower percentage can reflect this scope
change rather than a test regression. This is one platform/build's traceable
inventory, not a union of macOS/iOS or architecture-specific code. No numeric
coverage threshold is introduced.

### First integrated fork publication — under validation

- Repository/branch: **`AndreMiras/pyobjus:cython-coverage-proof`**.
- Commit: **`e3dcfbaf067f3f60d42270c5ce4490a048c9e31a`**.
- [Actions run 40124899719](https://github.com/AndreMiras/pyobjus/actions/runs/40124899719),
  macOS 26.6.2, arm64 execution, Python 3.14.8.
- [Coveralls job 190211394](https://coveralls.io/jobs/190211394),
  [build 82580195](https://coveralls.io/builds/82580195).
- Stored accounting: **1,180 covered / 642 missed / 1,822 executable**, **64.764%**.

The public build metadata, source-file inventory, and per-file coverage JSON arrays
were compared directly with the uploaded XML and retained manifest. **All 11 files
and every executable/hit/miss line state agree.** Counts below use repository paths
resolved from XML `<sources>` plus class filenames:

| Repository source | Covered | Missed | Executable |
| --- | ---: | ---: | ---: |
| `pyobjus/__init__.py` | 0 | 2 | 2 |
| `pyobjus/consts/__init__.py` | 0 | 105 | 105 |
| `pyobjus/consts/corebluetooth.py` | 0 | 6 | 6 |
| `pyobjus/dylib_manager.py` | 23 | 18 | 41 |
| `pyobjus/objc_py_types.py` | 98 | 5 | 103 |
| `pyobjus/protocols.py` | 1 | 0 | 1 |
| `pyobjus/debug.pxi` | 2 | 7 | 9 |
| `pyobjus/pyobjus.pyx` | 416 | 125 | 541 |
| `pyobjus/pyobjus_conversions.pxi` | 304 | 159 | 463 |
| `pyobjus/pyobjus_types.pxi` | 239 | 203 | 442 |
| `pyobjus/type_enc.pxi` | 97 | 12 | 109 |
| **Total** | **1,180** | **642** | **1,822** |

### Upload-path correction

The first upload stored shortened names such as `pyobjus_types.pxi` and
`consts/__init__.py`, omitting the repository's `pyobjus/` directory. Those names
match the XML class filenames, but reporter **0.6.22**'s Cobertura parser does not
compose them with the XML `<sources>` roots. The report's numerical totals are
correct while the stored filenames do not identify repository files.

The workflow now supplies the action's supported **`base-path: pyobjus`** input.
This uploader-boundary correction prefixes each filename to identify exactly the
same original source already validated through the XML roots. It preserves the
validated final XML, every line count, the policy, and the nonfatal upload policy.

Verification used the actual official **0.6.22** reporter binary, checksum verified,
with `--debug --dry-run` against the retained native XML. Without the prefix, the
payload reproduces all 11 shortened filenames and omits their source digests.
With the prefix, all 11 paths equal the repository-relative manifest paths, all
source digests match the retained/checked-out files, and every coverage array is
unchanged. **A new published run is required to validate this correction on the
service.** No upload was performed by these local dry runs.

Public JSON reads are available, but the HTML/source-view routes return a
Cloudflare managed challenge (HTTP 403) in this environment. Stored line states
have been verified; rendered original-source contents remain a publication check
after the corrected upload.

### Previous baseline and intended badge target

The README badge targets **`kivy/pyobjus:master`**. Its current public baseline is
[build 82574158](https://coveralls.io/builds/82574158), commit
`d630321471ae0a25fb46b48227aaee4e138257af`, from
[Actions run 40073722258](https://github.com/kivy/pyobjus/actions/runs/40073722258).
It has **124 covered / 134 missed / 258 executable Python lines**, **48.062%**, and
six Python files. It has not received the new compiled-source baseline.

In the new post-bootstrap run, the Python subtotal is **122/136/258**: package
initialization's two previous hits remain in the denominator as misses. Adding
the compiled **1,058/506/1,564** subtotal gives the overall **1,180/642/1,822**
result. The percentage change therefore compares different measurement scopes.

The upstream badge URL is retained. A corrected fork upload validates the fork;
the intended upstream result must be checked after this integration runs in
`kivy/pyobjus`. **No trusted published expanded baseline has been accepted yet.**
