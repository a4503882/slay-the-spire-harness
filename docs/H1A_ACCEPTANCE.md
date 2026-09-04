# H1-A acceptance report

## Result

H1-A passed its first complete isolated native one-combat probe on 2026-09-04.

- run ID: `h1a-20260904-182052-2cf48c53`
- seed: `AMIYA20260904`
- character / ascension: `IRONCLAD` / `0`
- run report:
  `artifacts/runs/h1a-20260904-182052-2cf48c53/h1-report.json`
- worker status: `passed`
- deterministic driver status: `passed`
- one combat completed: `true`
- offline replay: `REPLAY_VALID`
- normal-data guard unchanged: `true`
- normal-data changes: `0`
- owned Java stopped: `true`
- owned driver stopped: `true`
- sidecar descriptor removed: `true`
- unrelated matching game processes remaining after close: `0`
- independent H1-A verification: `valid=true`, `23/23` checks passed

This is automated protocol, native-state, isolation, and trace evidence. Under
the project acceptance boundary, operator acceptance remains Master's manual
step. The report does not claim H1-B's full Act 3 run or later model/UI work.

The independent verification artifact is
`artifacts/runs/h1a-20260904-182052-2cf48c53/h1-independent-verification.json`
with SHA-256
`67A4863DB4058CB2B984C0A109F75FCC7D03C1DA1B4B6BD776671F56E2B11C01`.

## Pinned environment

- environment fingerprint:
  `sha256:5032fda24a79ef6e7309f5de91c03909497280fe1fc3758195fe0bce91e670d7`
- Steam app / build: `646570` / `10180494`
- game JAR SHA-256:
  `CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673`
- ModTheSpire: `3.30.3`, SHA-256
  `541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604`
- BaseMod: `5.56.0`, SHA-256
  `C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF`
- bridge upstream commit:
  `5e417eb189530986b9047a3c9426889fb261d146`
- bridge version / protocol:
  `1.2.1-sts-harness.1` / `communicationmod-harness.v1`
- bridge JAR SHA-256:
  `683A47733B8AF84E7248189C2DC79AD4DD57EC5F03FBF08F1BA49F5F06C98D2C`
- enabled mods exactly: `basemod`, `CommunicationMod`

The environment document also fingerprints the Java runtime and every Python
module/script participating in launch, transport, normalization, action
resolution, execution, hashing, baseline control, and verification.

The game log confirmed `ModTheSpire (3.30.3)`,
`CommunicationMod (1.2.1-sts-harness.1)`,
`Communication Mod (StS Harness)`, the strict ready handshake, and game start.
The worker log confirmed both `H1_WORKER_READY` and `H1_WORKER_COMPLETE`.

## Public protocol and fairness boundary

The sidecar:

- bound only to `127.0.0.1` on an ephemeral port;
- used strict UTF-8 JSON-RPC 2.0 with a 4-byte unsigned big-endian length and a
  4 MiB maximum frame;
- placed a 256-bit controller nonce in a descriptor whose Windows ACL was
  restricted before the driver opened it;
- required the nonce for every mutation;
- required exact episode, native-session, run, decision, observation-hash, and
  legal-action-hash preconditions for every step;
- exposed no generic native-command submission method;
- removed the nonce-bearing descriptor during close.

The `player_visible.v1` projection omitted:

- native seed state;
- raw card UUIDs;
- raw `available_commands`;
- raw keyboard, coordinate, and wait controls;
- monster `last_move_id` and `second_last_move_id` history;
- draw-pile order (only a canonical multiset and count are exposed).

Card instances, monster targets, map nodes, decisions, rooms, combats, runs,
native sessions, and episodes use stable Harness identities. A fixture test
reprojects all eight retained M-1 states and checks the exercised main-menu,
event, map, and combat paths for hidden-state leakage.

Those identities are stable only within their native episode. Consequently,
`observation_hash` is a run-local integrity and stale-decision token: it is
expected to differ between two same-seed executions because it includes random
episode/session/run identities and run-local aliases. It is not evidence of
cross-run parity. H1-B must introduce a separately versioned identity-rebased
semantic checkpoint before claiming live replay parity; the run-local legal-
action, transition, and chain hashes cannot be used as a substitute.

## Native episode evidence

The sidecar received 19 raw messages, retained 18 distinct stable states, and
deduplicated one close-wakeup state. It emitted 17 chained transitions:

- event decisions: `3`;
- map decisions: `1`;
- combat decisions: `12`;
- post-combat reward decisions: `1`.

The deterministic policy submitted 16 typed actions:

- `choose_option`: `3`;
- `choose_map_node`: `1`;
- `play_card`: `9`;
- `end_turn`: `3`.

All 16 actions were accepted and independently verified; zero were rejected,
unverified, or contradicted by a bridge error. The native resolution audit
contains only semantic `choose`, `play`, and `end` commands. It contains no
`key`, `click`, or `wait` fallback.

The final transition is `combat_reward` on floor 1 at 69 HP. The last card play
has an explicit `combat_completed` event. Burning Blood raised HP from 63 to 69
on completion, which is consistent with the native post-combat state.

## Transition and replay evidence

Every transition contains:

- the exact player-visible observation and legal-action documents;
- pre-state and post-state raw/observation/legal-action hashes;
- the normalized submitted action batch and action result;
- action-specific semantic proof;
- a hash of the internally resolved native command;
- reward, terminal flags, metrics, transition hash, and chain hash.

The independent verifier did not trust those documents at face value. From the
retained raw-state sequence it regenerated every observation, legal-action set,
stable identity, native action resolution, and semantic action proof, then
compared them byte-semantically with the trace. It also recomputed every raw,
observation, legal-action, transition, and chain hash and rejected missing,
duplicated, reordered, or modified records.

Final chain hash:

`sha256:03266bb4e966dd1ceb8414248ea27c5ef471ac89cac5c4574a4a918e03e0fd55`

Relevant artifact SHA-256 values:

- `h1-report.json`:
  `AED036A7E349E3DE73E0942F14F4E0C24102946AE2DCF7BB468BB6134B0292BB`
- `replay.json`:
  `738E63525447BF2B6BAAFF4C6533D6971A7ADF54226397E7C82EA6ABEE6CC922`
- `transitions.jsonl`:
  `7ADA749D769673507072382B6C2E549561F4EA843DA20AD1C58C2837E467968F`

## Isolation and close evidence

The episode used a unique working directory and profile. It redirected the game
working directory, `LOCALAPPDATA`, `APPDATA`, `USERPROFILE`, Java `user.home`,
ModTheSpire configuration, preferences, saves, logs, and bridge stderr. The game
JAR was a hard link to the verified one-copy cache; only BaseMod and the pinned
bridge were present in the isolated `mods` directory.

The normal-data guard covered the normal game installation and saves, Workshop
mods, normal ModTheSpire configuration, Steam app manifest, and discovered Steam
`localconfig.vdf` files. Before and after documents were byte-identical:

`sha256:670b40ac151554796e41e3fe35025e156fbad9432eabb5654eb8dcc1e511c2fb`

`env.close` authenticated the exact episode identity, requested worker closure,
and used an internal read-only `state` wakeup so the worker could finalize its
append-only artifacts and remove the descriptor. The owning launcher then
stopped its exact Java process tree and re-ran the external normal-data guard.
The driver exited with code 0; no matching Slay the Spire process remained.

## Automated checks

The final implementation gate passed:

- `46` Python tests;
- Python `compileall` for `src`, `tools`, and `tests`;
- PowerShell parser validation for `tools/run_h1a_probe.ps1`;
- clean Java compile/package/shade;
- bridge reproducible-build hash check.

The unit and fixture suite covers strict JSON parsing, framing limits, JSON-RPC
shape, loopback binding, controller authentication, subprocess worker lifecycle,
state projection, stable identities, hidden draw order, typed legal actions,
stale/forged action rejection, duplicate-state suppression, action-effect
proofs, transition/chain hashes, replay tamper detection, environment sealing,
M-1 behavior, normal-data guards, and bridge static/build invariants.

## H1-A boundary

This milestone provides:

- the public sidecar protocol;
- normalization and player-visible projection;
- stable identity mapping;
- typed legal actions and independent validation;
- `env.reset`, `env.observe`, `env.step`, and `env.close`;
- one complete fixed-seed native combat without OS input;
- transition audit and offline replay verification;
- unit and real-fixture coverage.

H1-B remains responsible for every remaining vanilla screen/action path, a full
Ironclad A0 run to native terminal state, complete metrics, repeated-seed live
parity, and the broader H1 acceptance corpus. H2 model adapters and command UI
have not started.
