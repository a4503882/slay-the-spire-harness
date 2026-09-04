# Slay the Spire Harness

Implementation workspace for the local Slay the Spire 1 Harness specified in
[`SPEC.md`](SPEC.md).

M-1 and H1-A are implemented and have passed isolated native probes. H1-A adds
the loopback framed JSON-RPC sidecar, player-visible state projection, stable
agent identities, typed legal actions with independent pre/post validation,
transition hash chaining, offline replay verification, and one complete
fixed-seed combat without changing normal saves or configuration. H1-B is the
next milestone.

## Current target

- Steam app `646570`
- Steam build `10180494`
- vanilla Ironclad, Ascension 0
- ModTheSpire `3.30.3`
- BaseMod `5.56.0`
- bridge fork based on CommunicationMod `1.2.1` upstream commit
  `5e417eb189530986b9047a3c9426889fb261d146`

No game binary or framework-mod JAR is stored in this repository.

## Checks

Run the complete project check, including the reproducible Java bridge build:

```powershell
.\tools\run_tests.ps1
```

For the Python and script checks without rebuilding the bridge:

```powershell
.\tools\run_tests.ps1 -SkipBridge
```

Direct pytest invocation is also supported. The subprocess worker test supplies
its own absolute `src` entry because pytest's `pythonpath` setting applies only
to the pytest process and is not inherited automatically by a child Python
process:

```powershell
python -m pytest -q
```

The real native probe is guarded separately:

```powershell
.\tools\run_m1_probe.ps1
```

The probe refuses to run while an unrelated Slay the Spire or matching Java
process is active. Its evidence remains under `artifacts\m1-runs`.

The first accepted evidence set is documented in
[`docs/M1_ACCEPTANCE.md`](docs/M1_ACCEPTANCE.md).

Run the H1-A public-API one-combat probe with:

```powershell
.\tools\run_h1a_probe.ps1
```

It rebuilds the pinned bridge, refuses to touch an already-running related game
process, fingerprints normal game/Steam/mod data, launches one isolated game and
sidecar, drives a deterministic Ironclad A0 combat only through typed JSON-RPC
actions, independently verifies the trace, then stops only its owned process
trees. Evidence is retained under `artifacts\runs`.

The first accepted H1-A evidence set is documented in
[`docs/H1A_ACCEPTANCE.md`](docs/H1A_ACCEPTANCE.md).

## H1-A public boundary

- transport: UTF-8 JSON-RPC 2.0 with unsigned 32-bit big-endian length frames;
- bind address: IPv4 loopback only;
- maximum frame: 4 MiB;
- mutations: controller nonce plus exact episode/session/run/decision and
  observation/legal-action hash preconditions;
- episode methods: `env.reset`, `env.observe`, `env.step`, and `env.close`;
- raw CommunicationMod commands, card UUIDs, monster move history, seed, and
  draw-pile order are not exposed to the policy-facing observation;
- H1-A accepts one typed action per `env.step`; native command resolution stays
  inside the sidecar and every success requires a distinct stable post-state.

### Hash scope warning

`observation_hash` is intentionally valid only inside one run. It hashes the
exact observation, including random episode/native-session/run identities,
decision identity, and run-local stable object aliases. Two fixed-seed runs can
be semantically identical and still have different `observation_hash` values;
that difference is expected. Use it for integrity and stale-decision protection,
never as an H1-B cross-run replay checkpoint.

H1-B live parity must use a separately versioned, identity-rebased semantic
checkpoint projection (or explicit normalized semantic-field comparison until
that projection exists). `legal_actions_hash`, `transition_hash`, and
`chain_hash` also bind run-local material and must not be substituted for that
cross-run checkpoint.

Offline trace verification can be rerun independently:

```powershell
$run = 'artifacts\runs\h1a-20260904-182052-2cf48c53'
python -m sts_harness.replay_verify --run-dir $run
python -m sts_harness.h1_verify --run-dir $run
```

Set `PYTHONPATH` to the repository's absolute `src` directory first when those
module commands are invoked outside pytest or `tools\run_tests.ps1`.
