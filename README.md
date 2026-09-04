# Slay the Spire Harness

Local, structured-control Harness for Slay the Spire 1 on Windows/Steam. The
native game remains authoritative: policies receive a versioned player-visible
observation and legal-action set, submit typed actions, and receive independently
verified post-state results. Pixels, OCR, mouse coordinates, raw keyboard input,
and arbitrary CommunicationMod commands are not part of the normal control loop.

The normative design is in [`SPEC.md`](SPEC.md).

## Current status

| Milestone | Status | Accepted evidence |
| --- | --- | --- |
| M-1 bridge compatibility | Passed | [`docs/M1_ACCEPTANCE.md`](docs/M1_ACCEPTANCE.md) |
| H1-A public API and one combat | Passed | [`docs/H1A_ACCEPTANCE.md`](docs/H1A_ACCEPTANCE.md) |
| H1-B complete vanilla environment and live replay | Passed | [`docs/H1B_ACCEPTANCE.md`](docs/H1B_ACCEPTANCE.md) |
| H1-C scripted random/greedy baselines | Passed | [`docs/H1C_SCRIPTED_ACCEPTANCE.md`](docs/H1C_SCRIPTED_ACCEPTANCE.md) |
| H1-C tactical solver | Not implemented | No result or performance claim |
| H2 model adapters and operator UI | Not started | Out of current scope |

Current Harness version: `0.3.0`. Current specification version:
`0.3.0-draft`.

## Supported target

- Windows, Steam app `646570`
- accepted Steam build `10180494`
- vanilla Ironclad, Ascension 0
- serial execution: one isolated native process per formal episode
- ModTheSpire `3.30.3`
- BaseMod `5.56.0`
- CommunicationMod fork `1.2.1-sts-harness.2`
- bridge protocol `communicationmod-harness.v2`
- bridge upstream base commit
  `5e417eb189530986b9047a3c9426889fb261d146`
- formal fairness profile `player_visible.v1`

No game binary, proprietary game asset, ModTheSpire JAR, or BaseMod JAR is
stored in this repository. Formal native runs validate the exact locally
installed target hashes before launch.

## Canonical project check

Run the complete Python, PowerShell, and Java bridge gate from the repository
root:

```powershell
.\tools\run_tests.ps1
```

It sets `PYTHONPATH` for the complete process tree, runs all Python tests and
`compileall`, parses every PowerShell script under `tools`, and reproducibly
builds the Java 8-compatible bridge.

To omit only the bridge rebuild:

```powershell
.\tools\run_tests.ps1 -SkipBridge
```

Do **not** use a bare `python -m pytest -q` as the project acceptance command.
Pytest's `pythonpath = ["src"]` setting affects the pytest process but is not
reliably inherited by worker subprocesses such as those exercised by
`test_m1_worker.py`. A bare run can therefore fail even when the canonical
process-tree configuration is correct.

Exact test counts and native-run results belong to the immutable milestone
acceptance reports linked above, so routine test additions do not make this
README stale. The current accepted bridge artifact is 358,413 bytes with
SHA-256:

```text
2C624F16E564902A572D421E2526E31271165B2B5B793861844DAAC76683B4DD
```

## Formal native runs

### Before running

For H1-B and H1-C, fully exit the interactive `steam.exe` client first. Steam
can independently update the guarded user `localconfig.vdf`, so the launcher
hard-stops at preflight while it is active. The Harness never closes Steam
itself. The background `SteamService.exe` alone is not a rejection condition.

The launcher also refuses to start when a related Slay the Spire/ModTheSpire
process is already active. Every accepted episode uses a unique profile/work
root, fingerprints the normal game/mod/Steam paths before and after execution,
and stops only its recorded owned Java/worker process chain.

### H1-C scripted baseline suite

Run the current versioned smoke suite:

```powershell
.\tools\run_h1c_scripted.ps1
```

The default configuration is
[`benchmarks/h1c-scripted-smoke.v1.json`](benchmarks/h1c-scripted-smoke.v1.json).
It runs both policies against the same fixed native seed in separate serial
processes:

- `scripted_random_legal` v1.0.0 uses a separately recorded policy seed and
  SHA-256 rejection sampling over canonically ordered semantic legal actions;
- `scripted_greedy` v1.0.0 uses player-visible integer heuristics and canonical
  semantic tie-breaking.

The suite keeps cases, outcomes, metrics, and integer/rational aggregates
separate by policy. It publishes no combined score, includes no H1-B acceptance
run, and makes no tactical-solver claim. The accepted one-seed smoke result is
contract/infrastructure evidence, not a statistically meaningful ranking.

Each policy choice is written to `policy-decisions.jsonl` with its candidate-set
hash, semantic selection, selection evidence, policy-state hashes, decision
hash, and chained decision hash. Independently verify an explicit suite
directory with:

```powershell
.\tools\verify_h1c_scripted.ps1 `
  -SuiteDir .\artifacts\h1c-scripted-corpus\h1c-scripted-smoke-v1-YYYYMMDD-HHMMSS
```

Accepted H1-C evidence is documented in
[`docs/H1C_SCRIPTED_ACCEPTANCE.md`](docs/H1C_SCRIPTED_ACCEPTANCE.md).

### H1-B source plus live replay

Run one complete H1-B source episode followed by a fresh-process, same-seed
semantic replay:

```powershell
.\tools\run_h1b.ps1 `
  -Seed AMIYA20260904 `
  -TimeoutSeconds 1200 `
  -MaxDecisions 800
```

The H1-B acceptance policy exercises the required Act 1 screen/action paths,
takes a boss reward, and then uses legal native `end_turn` actions in Act 2
until an authentic native defeat. This bounds infrastructure acceptance time;
it is deliberately labeled `h1b_acceptance` and is not an H1-C strength
baseline.

Evidence is written beneath `artifacts\h1b-runs` and
`artifacts\h1b-corpus`. The accepted corpus is indexed in
[`docs/H1B_ACCEPTANCE.md`](docs/H1B_ACCEPTANCE.md).

### Earlier compatibility probes

The lower-level milestones remain available for regression work:

```powershell
# Pinned bridge/game compatibility probe
.\tools\run_m1_probe.ps1

# Public JSON-RPC one-combat episode probe
.\tools\run_h1a_probe.ps1
```

Their accepted evidence is indexed in
[`docs/M1_ACCEPTANCE.md`](docs/M1_ACCEPTANCE.md) and
[`docs/H1A_ACCEPTANCE.md`](docs/H1A_ACCEPTANCE.md).

## Public H1 contract

- transport: UTF-8 JSON-RPC 2.0 with unsigned 32-bit big-endian length frames;
- bind address: IPv4 loopback only;
- maximum public frame: 4 MiB;
- mutation authentication: descriptor-held controller nonce;
- stale-state preconditions: exact episode, native session, run, decision,
  observation hash, and legal-action hash;
- episode methods: `env.reset`, `env.observe`, `env.step`, and `env.close`;
- one native command in flight per episode;
- every reported action success requires semantic post-state evidence;
- raw native-command submission is absent from the public API.

Initial typed actions cover:

- start run;
- play card and end turn;
- use or discard potion;
- choose a visible option or map node;
- select, remove, or confirm cards;
- proceed, skip, cancel, leave, or return through explicit semantics;
- buy a visible affordable item;
- choose a currently unlocked rest-site action.

Unknown actionable screens are explicit hard stops. They do not fall back to
keyboard, coordinates, blind waiting, debug mutation, or guessed native text.

### Player-visible fairness

Formal policies receive `sts-observation.v1` and the matching
`sts-legal-actions.v1`. They do not receive:

- native seed/RNG state;
- raw card UUIDs;
- raw `available_commands`;
- monster move-history IDs;
- hidden draw-pile order;
- controller nonce;
- save/profile paths;
- raw native commands or future trace records.

H1-C policies enforce this boundary again at their own input API and are
independently replayed from recorded public documents.

### Hash scope warning

`observation_hash` is deliberately **run-local**. The exact observation binds
random episode/native-session/run identities, decision identity, and run-local
stable aliases. Two semantically identical fixed-seed executions will normally
have different `observation_hash` values.

Use `observation_hash` for same-run integrity and stale-decision protection.
Never use it as a cross-run checkpoint. `legal_actions_hash`, `transition_hash`,
and `chain_hash` also bind run-local material and are trace-integrity hashes,
not cross-run parity hashes.

H1-B live parity instead uses `sts-replay-checkpoint.v1`, a separately
versioned identity-rebased semantic projection. It keeps actionable hand and
card-in-play values strict, treats inactive combat piles as semantic multisets,
and excludes only the documented stale native caches in those inactive zones.
The exact projection contract is embedded in every checkpoint.

## Evidence and artifacts

Runtime evidence is local and ignored by Git:

| Evidence | Default path |
| --- | --- |
| bridge build report | `artifacts\build\bridge-build.json` |
| M-1 probe | `artifacts\m1-runs\...` |
| H1-A episode | `artifacts\runs\...` |
| H1-B episodes | `artifacts\h1b-runs\...` |
| H1-B corpus | `artifacts\h1b-corpus\...` |
| H1-C episodes | `artifacts\h1c-runs\...` |
| H1-C suite | `artifacts\h1c-scripted-corpus\...` |

Raw states are retained for independent reconstruction and marked
non-benchmark. They must never be copied into policy input. Public transition
artifacts omit the controller nonce, raw commands, native card UUIDs, and
native command strings.

The repository commits implementation, configuration, specifications,
acceptance indexes, and evidence hashes—not proprietary game files or large
native traces.

## Independent verification modules

The PowerShell wrappers are the preferred entry points because they configure
`PYTHONPATH`. For direct module use, set it explicitly first:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)

# One H1-A run
$h1aRun = '.\artifacts\runs\h1a-YYYYMMDD-HHMMSS-xxxxxxxx'
python -m sts_harness.replay_verify --run-dir $h1aRun
python -m sts_harness.h1_verify --run-dir $h1aRun

# One H1-B source/replay corpus
$h1bCorpus = '.\artifacts\h1b-corpus\h1b-YYYYMMDD-HHMMSS'
python -m sts_harness.h1b_verify --corpus-dir $h1bCorpus

# One H1-C scripted suite
$h1cSuite = '.\artifacts\h1c-scripted-corpus\h1c-scripted-smoke-v1-YYYYMMDD-HHMMSS'
python -m sts_harness.h1c_verify --suite-dir $h1cSuite
```

Replace the timestamp/`xxxxxxxx` placeholders with explicit artifact IDs. Do
not silently select the newest directory as acceptance evidence: failed and
rejected development runs are intentionally retained alongside accepted runs.

## Repository layout

```text
benchmarks/                 Versioned benchmark/smoke-suite configurations
docs/                       Bridge provenance and accepted milestone reports
src/sts_harness/            Public H1 runtime, replay, metrics, and policies
tests/                      Unit, fixture, tamper, lifecycle, and report tests
tools/                      Canonical PowerShell and Python entry points
vendor/CommunicationMod/    Pinned bridge fork source; build output is ignored
artifacts/                  Local runtime evidence; contents are ignored by Git
SPEC.md                     Normative protocol and milestone specification
```

## Current scope boundary

Implemented scope remains vanilla Ironclad A0 on the accepted Windows/Steam
target. The following are not current results:

- Silent, Defect, Watcher, or Ascension 1-20;
- Act 4/Heart benchmark completion;
- parallel native episodes;
- content-mod benchmarks;
- tactical solver performance;
- paid-provider/model evaluation;
- operator command-center or UI acceptance.

Adding any of those requires a separately versioned configuration/specification
and new acceptance evidence. Existing H1/H1-C results must not be relabeled or
silently reused for the wider scope.
