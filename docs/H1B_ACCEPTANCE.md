# H1-B acceptance report

## Result

H1-B passed its first complete isolated native source/replay corpus on
2026-09-04.

- corpus ID: `h1b-20260904-223836`
- source run ID: `h1b-full-20260904-223854-5192d5fc`
- replay run ID: `h1b-replay-20260904-224338-baf3b7f4`
- seed: `AMIYA20260904`
- character / ascension: `IRONCLAD` / `0`
- source status: `passed`
- native terminal outcome: `DEFEAT_COMBAT`, Act 2 floor 18
- replay status: `REPLAY_PARITY`
- compared checkpoints: `232/232`
- replayed actions: `231/231`
- first divergence: `null`
- environment fingerprint match: `true`
- source and replay normal-data guards unchanged: `true`
- source and replay residual related processes: `0`
- independent H1-B verification: `valid=true`, no failures

The corpus report is
`artifacts/h1b-corpus/h1b-20260904-223836/h1b-report.json`; its SHA-256 is
`ACB7E9857F10DE5A8D634E75DB11E1DD6C8E74E73EC7DD6DB536E11482880F8A`.
The independent verification artifact is
`artifacts/h1b-corpus/h1b-20260904-223836/h1b-independent-verification.json`;
its SHA-256 is
`8FAC059F10436C122C2A2D23B3BCF13368727A8BE2CC9B7ECE97A7E3C61E4394`.

This is automated protocol, native-state, isolation, replay, and artifact
evidence. Under the project acceptance boundary, operator acceptance remains
Master's manual review. H1-C baselines and H2 model/UI work are not claimed.

## Pinned environment

- environment fingerprint:
  `sha256:64664663395c5eecdfd43a5eced4a53ca73f6d8ab0f3bb750749da5f7966c7ed`
- Steam app / build: `646570` / `10180494`
- game JAR SHA-256:
  `CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673`
- game executable SHA-256:
  `44B8EACFD3843A8666E980DC9C71A50A069EF58610FB134464D1B606434C9603`
- ModTheSpire: `3.30.3`, SHA-256
  `541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604`
- BaseMod: `5.56.0`, SHA-256
  `C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF`
- bridge upstream commit:
  `5e417eb189530986b9047a3c9426889fb261d146`
- bridge version / protocol:
  `1.2.1-sts-harness.2` / `communicationmod-harness.v2`
- bridge JAR SHA-256:
  `2C624F16E564902A572D421E2526E31271165B2B5B793861844DAAC76683B4DD`
- Harness version: `0.2.0`
- fairness profile: `player_visible.v1`
- observation / legal-action / transition schemas:
  `sts-observation.v1` / `sts-legal-actions.v1` / `sts-transition.v1`
- replay checkpoint schema: `sts-replay-checkpoint.v1`
- enabled mods exactly: `basemod`, `CommunicationMod`
- Java: `1.8.0_144`; Python: `3.10.11`

The source and replay environment documents are byte-semantically identical
and fingerprint every Harness source/tool participating in launch, transport,
normalization, action resolution, execution, metrics, hashing, and replay.

## Native source episode

The source episode ran from `2026-09-04T22:38:56+08:00` to
`2026-09-04T22:43:37+08:00`. It used only structured JSON-RPC actions and the
native game as authority. After covering every required Act 1 path and taking a
boss relic, the acceptance policy used only legal `end_turn` actions in Act 2
until an authentic native combat defeat. The report records this bounded
infrastructure strategy as `act2_end_turn_until_native_defeat`; it is not an
H1-C strength baseline.

The run emitted 232 chained transitions from 234 distinct stable states and
deduplicated two repeated states. Its 231 typed actions were all accepted and
semantically verified:

- accepted / attempted: `231/231`
- rejected: `0`
- skipped: `0`
- unverified: `0`
- partial batches: `0`
- bridge errors: `0`
- unsupported screens: `0`

The live action surface exercised:

- `buy_item`
- `choose_map_node`
- `choose_option`
- `end_turn`
- `play_card`
- `proceed`
- `remove_card`
- `rest_site_action`
- `return_or_skip`
- `select_cards`
- `use_potion`

The live decision surface exercised:

- `neow`
- `combat`
- `card_reward`
- `combat_reward`
- `map`
- `event`
- `shop`
- `rest`
- `treasure`
- `boss_reward`
- `grid_select`
- `game_over`

This directly satisfies the required live combat, card-reward, map, event,
shop, rest, treasure, and boss-reward paths. The unit/fixture suite separately
covers main menu/reset, room completion, hand selection, exact and any-number
grid cardinality, targeted and untargeted cards/potions, discard-potion actions,
Act 3 victory, and unknown actionable screens.

Fixture provenance is recorded in `tests/fixtures/h1b/provenance.json` under
`sts-fixture-provenance.v1`. It labels the set as synthetic contract fixtures
for `player_visible.v1`, explicitly declares that raw hidden state is present,
and forbids use in model prompts, policy observations, or benchmark inputs. The
full-potion-inventory cases also preserve the accepted upstream limitation and
the Harness behavior that suppresses an unverifiable silent potion claim.

The final episode metrics include:

- rooms entered / completed: `20/19`
- combats entered / completed: `7/7`
- combat turns: `46`
- final HP / maximum HP: `0/83`
- final gold: `217`
- cards added / removed / upgraded: `8/1/2`
- relics acquired: `2`
- potions acquired / used / discarded: `3/1/0`
- native score: `150`
- process wall time: `263532 ms`

All model-call, token, and model-latency fields are explicitly `null` because
H1-B uses a scripted acceptance policy and no model provider. They are not
misreported as zero.

The final source chain hash is:

`sha256:ebcebb85eabedafcf5c92d6909658dc58dfa9ded2120e0d2b7074242b2d9e345`

## Same-seed live replay

The replay used a fresh isolated Java/game process and sidecar with the exact
source environment fingerprint. It resolved each recorded semantic action
selector against the new run's current legal-action set and compared every
`sts-replay-checkpoint.v1` document.

- source transitions / compared checkpoints: `232/232`
- source actions / replayed actions: `231/231`
- first divergence: `null`
- final recorded checkpoint:
  `sha256:6d9534c82ff83c58b50352fb86452180103b3de0dad433311a52728aacda97ab`
- final replayed checkpoint:
  `sha256:6d9534c82ff83c58b50352fb86452180103b3de0dad433311a52728aacda97ab`
- replay final chain hash:
  `sha256:422936227e2351002da5b311ed1afca21956889282b6c3df21d81e33a8bc63d0`

All 232 corresponding run-local `observation_hash` values differed. That is
expected and is positive evidence that the replay did not misuse them as
cross-run checkpoints. The exact observations include random episode/session/
run identities and run-local aliases. Cross-run parity comes only from the
versioned identity-rebased checkpoint projection. The source and replay chain
hashes also differ by design because each chain binds its own run-local trace.

## Independent verification

The independent verifier returned `valid=true` with:

- corpus-level checks: `15/15` true
- source-run checks: `32/32` true
- replay-run checks: `32/32` true
- failures: `0`

It independently rebuilt observations and legal-action sets from retained raw
states; re-resolved native actions; recomputed semantic action proofs, canonical
document hashes, transition hashes, chain hashes, and replay checkpoints; and
compared the corpus's embedded reports with their source files. It confirmed:

- every reported action result is verified and matches the transition audit;
- no player-visible document contains a forbidden hidden key;
- no `key`, `click`, `wait`, or generic native-command fallback was used;
- source and replay offline traces are both `REPLAY_VALID`;
- live replay compared every checkpoint and replayed every action;
- action selectors and final checkpoint hashes match;
- both combat metrics satisfy
  `0 <= combats_completed <= combats_entered`;
- missing model metrics are explicitly unavailable;
- normal guards, descriptor ACLs, cleanup, and process ownership checks pass.

## Isolation and lifecycle evidence

The launcher hard-stopped while interactive Steam was active during preflight
testing and never terminated Steam itself. The accepted corpus started only
after `steam.exe` was absent. `SteamService.exe` is not treated as the
interactive client.

Both formal episodes used unique profile/work roots. Each materialized the
verified game JAR as a hard link to the one-copy cache and exposed exactly the
accepted BaseMod and CommunicationMod JARs. The external normal-data guard
covered five discovered roots:

- normal game installation, including preferences, saves, and
  `betaPreferences`;
- Workshop content for app `646570`;
- normal ModTheSpire configuration;
- Steam app manifest `646570`;
- the applicable Steam-user `localconfig.vdf`.

For both source and replay, the before and after guard documents were
byte-identical. Each has SHA-256:

`480A0477C06A0CC4E39FD5AD8BED3599B037F5A96E35887A68A34829FFB24FE3`

The internal canonical guard digest was also identical before and after:

`sha256:ff0185b44640194da3df53f84ada7688f6fe9b5fc772c8025b7cabb89c15fc05`

The source and replay used separate Java PIDs and separate worker PIDs. Each
worker's creation time and Java parent PID were recorded before cleanup.
Authenticated close completed, both owned Java/worker processes stopped, each
nonce-bearing sidecar descriptor was removed, and no related process remained.
No unrelated process was targeted or terminated.

## Failure and unsupported behavior

The automated suite proves failure paths separately from the successful native
corpus:

- strict worker EOF produces an explicit failed summary;
- authenticated abort exits without requiring a new native-state wakeup;
- unknown actionable screens normalize to `unsupported`, expose no policy
  action, and truncate explicitly;
- stale/foreign decisions, forged payloads, extra fields, missing payloads, and
  invalid field types are rejected;
- sequential batches retain accepted prefixes, mark skipped suffixes, and emit
  explicit partial-success evidence;
- cleanup refuses to terminate a PID whose creation time or recorded parent no
  longer matches the owned worker identity;
- guard changes, environment mismatch, unresolvable replay actions, and first
  checkpoint divergence remain distinct report outcomes.

The accepted source/replay corpus itself contains no launch error, timeout,
unsupported screen, unverified action, or replay divergence.

## Artifact integrity

Relevant local artifact SHA-256 values:

- source `episode-report.json`:
  `970A8107F48D14792F1914CA399865726DA5C46EBC540435F9B6ED6FB5817AB9`
- source `metrics.json`:
  `B540F494AAD3F48DA01284CF703C1C4F78EB1205A5B9B4DB3DFEC80F8D871ACE`
- source `transitions.jsonl`:
  `E3267E185B1831B1C4577E382012138B999C5AC495F2195BB3E191AA6E840E02`
- source `actions.jsonl`:
  `98F5E23586F28B8758802E1A9608C921B20933550A9ABB72B854379C4FED9822`
- source `raw-states.jsonl`:
  `339C65BF27637994BE1EBEB35B1BE381FB61A32220AEF36CDB9F9CAFCBEBC180`
- replay `episode-report.json`:
  `5C2A83B4BE60A1177C018778605E09B644EDD2C4C27B6C3D9B6D8F9FAE35424D`
- replay `live-replay.json`:
  `BF514EBA9DF8B63DF0920BC89DA8D51CC12F208D80035AA438165D334C4DF5D8`
- replay `transitions.jsonl`:
  `D7D2D5E80C177562422DDF86DB9700EC5EDDF46E669028629B7F79A8C9E0AFF4`

Raw-state artifacts are explicitly marked non-benchmark and are retained only
for independent reconstruction and debugging. Public transition artifacts omit
the controller nonce, raw available commands, native card UUIDs, and native
command strings.

## Automated project checks

The canonical `tools/run_tests.ps1` gate passed on the accepted implementation:

- `104` Python tests;
- Python `compileall` for `src`, `tools`, and `tests`;
- PowerShell AST parsing for every script under `tools`;
- clean Java 8 compile/package/shade of 38 bridge source files;
- bridge build version, size, and SHA-256 checks.

A bare `python -m pytest -q` is not the project acceptance command because
pytest's `pythonpath = ["src"]` setting does not reliably propagate to worker
subprocesses. The canonical wrapper sets `PYTHONPATH` for the entire process
tree before running tests.

## H1-B boundary

This milestone provides:

- the complete initial vanilla screen/action environment for Ironclad A0;
- isolated one-process-per-episode launch and exact process ownership;
- a full native episode to an authentic terminal state;
- complete episode metrics and artifact summaries;
- identity-rebased, same-seed live replay with full required checkpoint parity;
- explicit unsupported-screen, crash, abort, and validation failure behavior;
- exact pre/post normal-data and installation guards.

H1-C scripted/tactical baseline evaluation and H2 model adapters/operator UI
remain future work.
