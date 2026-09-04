# Slay the Spire Harness

Implementation workspace for the local Slay the Spire 1 Harness specified in
[`SPEC.md`](SPEC.md).

M-1 and H1-A are implemented and have passed isolated native probes. H1-A adds
the loopback framed JSON-RPC sidecar, player-visible state projection, stable
agent identities, typed legal actions with independent pre/post validation,
transition hash chaining, offline replay verification, and one complete
fixed-seed combat without changing normal saves or configuration. H1-B adds the
complete vanilla screen/action surface, one-process-per-episode launcher,
metrics, explicit failure behavior, and identity-rebased same-seed live replay.

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

Do not use a bare `python -m pytest -q` as the project acceptance command.
Pytest's `pythonpath = ["src"]` modifies the pytest process, but that setting is
not automatically inherited by worker subprocesses such as those exercised by
`test_m1_worker.py`. The canonical wrapper above sets `PYTHONPATH` for the whole
process tree and also runs compile/build checks.

Run the formal H1-B source plus fresh-process same-seed replay with:

```powershell
.\tools\run_h1b.ps1 -Seed AMIYA20260904 -TimeoutSeconds 1200 -MaxDecisions 800
```

The interactive `steam.exe` client must be closed first. It writes the guarded
user `localconfig.vdf` independently while active, so the launcher hard-stops at
preflight instead of launching a run whose exact normal-data guard cannot be
trusted. It never closes Steam itself and does not reject `SteamService.exe`.
Evidence is retained under `artifacts\h1b-runs` and
`artifacts\h1b-corpus`.

The acceptance driver completes every required Act 1 path, consumes a boss
reward, then uses legal native `end_turn` actions in Act 2 until an authentic
native defeat. This bounds infrastructure acceptance time; it is explicitly not
an H1-C strength baseline.

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

H1-B live parity uses `sts-replay-checkpoint.v1`, a separately versioned,
identity-rebased semantic projection. It removes run-local identity, treats
non-hand combat piles as semantic multisets, and ignores cached
`damage`/`block`/turn-cost/playability/free-play/retain values only while a card
is outside the hand or card-in-play slot; those values remain strict while they
are actionable. The projection contract is embedded in each checkpoint.
`legal_actions_hash`, `transition_hash`, and `chain_hash` still bind run-local
material and must not be substituted for the cross-run checkpoint.

Offline trace verification can be rerun independently:

```powershell
$run = 'artifacts\runs\h1a-20260904-182052-2cf48c53'
python -m sts_harness.replay_verify --run-dir $run
python -m sts_harness.h1_verify --run-dir $run
```

An H1-B corpus is independently verified with:

```powershell
$corpus = 'artifacts\h1b-corpus\h1b-YYYYMMDD-HHMMSS'
$env:PYTHONPATH = (Resolve-Path .\src)
python -m sts_harness.h1b_verify --corpus-dir $corpus
```

Set `PYTHONPATH` to the repository's absolute `src` directory first when those
module commands are invoked outside pytest or `tools\run_tests.ps1`.
