# H1-C scripted-baseline acceptance report

## Result

The H1-C scripted subset passed its first complete isolated native suite on
2026-09-05.

- suite ID: `h1c-scripted-smoke-v1`
- suite directory: `h1c-scripted-smoke-v1-20260905-014815`
- native seed matrix: `AMIYA20260904`
- character / ascension: `IRONCLAD` / `0`
- fairness profile: `player_visible.v1`
- policies: `scripted_random_legal`, `scripted_greedy`
- policy versions: `1.0.0`, `1.0.0`
- suite status: `passed`
- cases run / configured: `2/2`
- native terminal cases: `2/2`
- truncated / failed / not-run cases: `0/0/0`
- same environment for every case: `true`
- same native-seed matrix for every policy: `true`
- combined score present: `false`
- H1-B acceptance runs included: `false`
- independent verification: `valid=true`, no failures or case errors
- tactical solver: `not_implemented`, no performance claim

The accepted suite report is
`artifacts/h1c-scripted-corpus/h1c-scripted-smoke-v1-20260905-014815/suite-report.json`;
its SHA-256 is
`93C733D3DA1A98FE20A47B6844BF40153EDC158B77B0FB3D5CCEECDEC66A0E5D`.

The independent verification artifact is
`artifacts/h1c-scripted-corpus/h1c-scripted-smoke-v1-20260905-014815/h1c-independent-verification.json`;
its SHA-256 is
`DDC2604DC74F4CC36E48AAC44D5B6496B10F9F4AD35B2D1CA1AAF13FA85FE7F8`.

This is automated protocol, policy, native-state, isolation, metric, and audit
evidence. Operator acceptance remains Master's manual review. The suite has one
native seed and is an infrastructure/contract smoke baseline, not a statistical
claim that one policy is generally stronger.

## Versioned suite configuration

The tracked configuration is `benchmarks/h1c-scripted-smoke.v1.json`, copied
verbatim by value to the suite as `suite-config.json`.

- schema: `sts-scripted-baseline-suite.v1`
- suite ID: `h1c-scripted-smoke-v1`
- native seeds: `AMIYA20260904`
- maximum decisions per episode: `2000`
- maximum wall time per episode: `1800 seconds`
- native terminal required: `true`
- canonical suite-config hash:
  `sha256:3abcbefd0f0a60556538914d49a19e8b5a808a9bdefc6f6d8e9816ed71221e54`
- formatted `suite-config.json` file SHA-256:
  `3FBFD673F9143F3CFA04884544505DF2E700F458D343014F6078FC7ECFC7EDF2`

The runner validates the configuration with exact-field semantics. Unknown
fields, duplicate or missing policies, wrong policy versions, invalid seeds,
non-Ironclad/non-A0 targets, non-player-visible fairness, invalid limits, or a
non-terminal initial acceptance mode are rejected before native execution.

## Policy contracts

### Random legal

`scripted_random_legal` version `1.0.0` uses:

- policy seed: `AMIYAH1CRANDOMV1`
- algorithm: `sha256-rejection-v1`
- candidate order: canonical semantic action UTF-8 bytes, ascending
- action-type filtering: none
- tactical solver: false

At every non-terminal decision it represents each legal action only by action
type plus `sts-action-selector.v1`, rejects duplicate semantic candidates, sorts
the candidates canonically, and hashes the candidate set. SHA-256 draw material
contains the separate policy seed, zero-based policy decision index,
candidate-set hash, and retry counter. Rejection sampling maps the accepted
digest to the candidate range without an undocumented modulo-bias rule.

The random policy never receives the native seed, raw bridge state, native
commands, or save data. Its policy seed is benchmark configuration, not hidden
game state.

### Deterministic greedy

`scripted_greedy` version `1.0.0` uses:

- algorithm: `integer-score-canonical-tie-v1`
- score type: integer
- tie-break: lowest canonical semantic candidate index
- policy seed: null
- tactical solver: false

Its simple player-visible heuristics cover combat, potions, paths, rewards,
shops, rest sites, events, card selection/removal, and boss relics. Equal
integer scores never use `action_id`, decision ID, card-instance ID, or native
collection index. Its only retained private state is the set of visited shop
locations represented by public act/floor keys; before/after state and state
hashes are included in every affected policy decision.

The greedy policy continues ordinary play until native victory/defeat or an
explicit suite limit. It does not inherit the H1-B acceptance driver's
`act2_end_turn_until_native_defeat` behavior.

## Public-input fairness boundary

The policy API accepts exactly two documents:

- `sts-observation.v1` with `fairness_profile=player_visible.v1`;
- the matching `sts-legal-actions.v1` document.

Before every choice it verifies both document hashes and their binding. It
recursively rejects raw/native keys including:

- `seed`
- `uuid`
- `available_commands`
- `last_move_id`
- `second_last_move_id`
- `native_command`
- `controller_nonce`
- `raw`

The policy code has no bridge client or native-command interface. Only the
outer baseline driver submits the selected public action through `env.step`,
which retains all H1 stale-state preconditions and semantic post-state proof.

## Native results

Both policies ran the same native seed in separate, serial, isolated processes.
The observed one-seed results are:

| Metric | `scripted_random_legal` | `scripted_greedy` |
| --- | ---: | ---: |
| Native outcome | `DEFEAT_COMBAT` | `DEFEAT_COMBAT` |
| Final act / floor | 1 / 3 | 2 / 30 |
| Final HP / max HP | 0 / 80 | 0 / 92 |
| Native score | 19 | 278 |
| Stable decisions | 60 | 487 |
| Policy decisions | 59 | 486 |
| Accepted / attempted actions | 59 / 59 | 486 / 486 |
| Rejected / skipped / unverified | 0 / 0 / 0 | 0 / 0 / 0 |
| Combats completed / entered | 3 / 3 | 15 / 15 |
| Combat turns | 17 | 71 |
| Rooms completed / entered | 3 / 4 | 31 / 32 |
| Offline replay | `REPLAY_VALID` | `REPLAY_VALID` |

The per-policy aggregates retain integer numerator/denominator pairs rather
than floating-point averages. With one case per policy, the recorded final-floor
ratios are `3/1` and `30/1`, and native-score ratios are `19/1` and `278/1`.
No aggregate combines policy modes.

The random case is
`h1c-random-legal-20260905-014832-d2b601e7`. Its transition chain ends at:

`sha256:d8d828e213c3d5910f6610e8da454fb22bb31c62751d9c7badcaf1e573e055ad`

Its policy-decision chain ends at:

`sha256:02146855b0c672accb22a403891c7a32b67e71c9184490c11383a669cc9f4587`

The greedy case is `h1c-greedy-20260905-015019-98aa2508`. Its transition
chain ends at:

`sha256:9f3354eebb9d67ecdf97a9023bda29ebab332be9b700546559b9b65ba578ecf0`

Its policy-decision chain ends at:

`sha256:cc474ae8dfe3bd36c72e50756e740f110ce64ba847b5fe30c07a3d163b122d0a`

All model-call, token, model-repair, and model-latency fields are explicitly
`null`; they are not misreported as zero.

## Policy-decision audit

Every selection is retained as `sts-scripted-policy-decision.v1` before its
native action is submitted. Each row binds:

- policy ID and version;
- policy decision index and pre-transition index;
- observation, legal-action, and replay-checkpoint hashes;
- canonical candidate count and candidate-set hash;
- selected semantic action;
- random-draw or greedy-score evidence;
- policy state before and after, plus their hashes;
- decision hash, previous chain hash, and decision-chain hash.

The independent verifier instantiated a fresh policy and replayed it over each
recorded public observation/legal-action pair in order. It reproduced all 59
random decisions and all 486 greedy decisions exactly, matched each selected
semantic action to the independently verified H1 action result, and recomputed
both complete policy-decision chains.

## Independent verification

`tools/verify_h1c_scripted.ps1` returned `valid=true` with:

- suite checks: `15/15` true
- random episode H1 checks: `29/29` true
- greedy episode H1 checks: `29/29` true
- random policy-audit checks: `6/6` true
- greedy policy-audit checks: `6/6` true
- failures: `0`
- case errors: `0`

For each episode it independently rebuilt raw-state normalization, legal
actions, native action resolution, semantic action proofs, transition hashes,
chain hashes, and offline replay. It additionally confirmed:

- exact suite config and canonical config hash;
- exact policy descriptors and baseline identities;
- same seed matrix and same environment fingerprint;
- no player-visible hidden key or forbidden native control;
- every action accepted and semantically verified;
- all metrics identical to the worker summary;
- no model metric presented as zero;
- normal guards and their before/after documents identical;
- descriptor ACL restricted;
- owned Java and worker stopped;
- sidecar descriptor removed;
- no residual related process;
- policy aggregates independently recomputed;
- combined score absent and explicitly prohibited;
- H1-B runs excluded;
- tactical solver not included or claimed.

## Pinned environment and isolation

Both cases used environment fingerprint:

`sha256:6957e19685ababde0a2d62759dd3e839cc58de1cd832d90aa01fabbf5027554b`

Their `environment.json` files are byte-identical, each with SHA-256:

`5F1BFE6E93A570A4D3A860D8EBF1656C346121D433FCB7511E1663F48078FDC8`

The environment records Harness `0.3.0`, Python `3.10.11`, Java 8, the accepted
Steam build, exact game/ModTheSpire/BaseMod hashes, bridge
`1.2.1-sts-harness.2`, protocol `communicationmod-harness.v2`, and exactly
`basemod,CommunicationMod`.

After verification, the current workspace's 46 environment-sealed `src` and
`tools` files matched the recorded hashes exactly: no changed, added, or missing
file. The bridge JAR remained 358,413 bytes with SHA-256:

`2C624F16E564902A572D421E2526E31271165B2B5B793861844DAAC76683B4DD`

Both cases used unique profile/work roots, a hard link to the verified one-copy
game-JAR cache, and only the accepted mods. Interactive Steam was absent at
preflight. The same five-root normal-data guard used by accepted H1-B covered
the normal game tree, Workshop mods, ModTheSpire config, Steam manifest, and
applicable Steam `localconfig.vdf`.

For both episodes the before/after guard documents were byte-identical, each
with SHA-256:

`480A0477C06A0CC4E39FD5AD8BED3599B037F5A96E35887A68A34829FFB24FE3`

Their canonical guard digest was unchanged:

`sha256:ff0185b44640194da3df53f84ada7688f6fe9b5fc772c8025b7cabb89c15fc05`

The episodes used distinct Java/worker PIDs with recorded creation time and
parent ownership. Authenticated close completed, both process pairs stopped,
both nonce-bearing descriptors were removed, and a final process scan found no
related process. No unrelated process was targeted.

## Rejected development runs

Two earlier native suites were correctly rejected before the accepted corpus:

1. A bridge grid-selection state exposed `confirm_up=true` while retaining an
   empty `selected_cards` list. The first greedy implementation trusted the
   incomplete list, selected `cancel`, and alternated between select/cancel until
   `TRUNCATED_DECISION_LIMIT` at 2000 decisions.
2. At a low-HP map with one Elite child, the Elite scored below zero while the
   non-progress `return` action inherited zero. Greedy alternated between map
   return and leaving the prior shop until the same explicit limit.

Both rejected episodes still passed offline replay, normal-data guard, and
owned-process cleanup; neither was included in accepted results. Regression
tests now require a current legal `confirm` to be taken even when the upstream
selected-card list is empty, and require a current map child to outrank
non-progress return regardless of its risk score.

## Artifact integrity

Relevant accepted artifact SHA-256 values:

- random `episode-report.json`:
  `745D8F9C90F7F45CEB82A15480BAB7D30223854CF7F3E263B3E39F6AE2F23A89`
- random `metrics.json`:
  `1856C0CB4937FFA5692F07162CD8BC83AC884272509C2973469BDDE515DF65CF`
- random `transitions.jsonl`:
  `7CF45D09385C8179A600753F1B899FD8ED3774947B634A7F085B0B95DCE5F8D4`
- random `policy-decisions.jsonl`:
  `7CED263EDBEBCC48A8534758C58761F8887A55EC9E8EF29419A901785A5E6BB8`
- greedy `episode-report.json`:
  `B99EA95F0DF7FDC66AD1F9C1299C6D67278DDD991866F03DEDE0D7FDB11770C4`
- greedy `metrics.json`:
  `55D277C089A0FF4E0C47F0119A1048583F6BA8BCB97291EED5504710376C2138`
- greedy `transitions.jsonl`:
  `0D2627B8595CCC23700D871ED5C1BBC99BBA61C1732E93FB585D381AC3B4EAAB`
- greedy `policy-decisions.jsonl`:
  `7803B3CA6435624FFE0B3956D77E2FCF0593C1315C1A6A88939B57FDAA2162E8`

Raw traces remain local, ignored, and explicitly non-benchmark. They are used
only by independent reconstruction and debugging, never as policy input.

## Automated project checks

The final canonical `tools/run_tests.ps1` gate passed before the accepted
native suite:

- `126` Python tests;
- Python `compileall` for `src`, `tools`, and `tests`;
- PowerShell AST parsing for every script under `tools`;
- clean Java 8 compile/package/shade of 38 bridge source files;
- bridge version, size, and SHA-256 checks.

New coverage includes exact suite-config rejection, policy-seed validation,
canonical candidate ordering, duplicate selector rejection, hidden input
rejection, deterministic random reconstruction, greedy run-local-ID
independence, public shop memory, no H1-B terminal shortcut, selection-confirm
and map-progress regressions, policy decision/chain tamper detection, serial
same-seed orchestration, failure/not-run retention, separated aggregates, and
embedded case-list verifier handling.

As with H1-B, a bare `python -m pytest -q` is not the project acceptance command.
The canonical wrapper supplies `PYTHONPATH` to worker subprocesses and performs
the remaining build/parse checks.

## H1-C scripted boundary

This accepted subset provides:

- a versioned deterministic random-legal policy;
- a versioned deterministic greedy policy;
- public-input-only policy execution;
- one isolated native process per policy/seed case;
- append-only, independently reproducible policy decision chains;
- separate per-policy cases, outcomes, metrics, and integer/rational aggregates;
- explicit truncation/failure/not-run retention;
- no blended score and no H1-B acceptance-result reuse;
- canonical runner and independent verifier commands.

The optional tactical solver adapter is not implemented. H2 model adapters and
the operator command center remain future work.
