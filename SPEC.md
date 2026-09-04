# Slay the Spire Harness Specification

| Field | Value |
| --- | --- |
| Specification version | `0.3.0-draft` |
| Target game | Slay the Spire 1 for Windows/Steam |
| Initial gameplay scope | Vanilla Ironclad, Ascension 0 |
| Initial integration | ModTheSpire + BaseMod + a pinned CommunicationMod-compatible bridge |
| Primary control mode | Structured internal state and structured actions |
| Status | M-1, H1-A, H1-B, and H1-C scripted baselines automatically verified; optional tactical solver not started |

## 1. Normative language

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
and **MAY** are normative requirements.

An implementation is not conformant merely because it can move through the
game. It is conformant only when it preserves the observation, action,
isolation, audit, replay, and acceptance boundaries in this document.

## 2. Objective

Expose the supported local Slay the Spire process as a quantified episode
environment suitable for scripted policies, search policies, LLM policies, and
human-supervised live play.

The native game remains authoritative. The Harness observes a versioned
projection of native state, publishes an independently validated legal-action
set, accepts typed actions with explicit state preconditions, and verifies the
result after the game reaches its next stable decision state.

Pixels, OCR, mouse coordinates, and operating-system input are not part of the
normal agent control loop. A screenshot MAY be attached as player-visible
context, but it MUST NOT expand action authority or replace structured state.

The first formal deliverable is a complete pre-model environment, called H1.
Model backends and the operator command center are H2 adapters over the same H1
contract.

## 3. Design principles

1. **Native authority.** The game performs card effects, damage, rewards,
   random rolls, room transitions, and victory or defeat. The Harness MUST NOT
   manufacture these results.
2. **Player-visible fairness.** Formal model evaluation receives only
   information available to a player under the configured fairness profile.
3. **Typed action authority.** A model never submits raw console text, key
   presses, or coordinates. It selects from or instantiates a current
   legal-action template.
4. **Fresh validation.** Every mutation is validated against the latest stable
   native state immediately before submission.
5. **No silent fallback.** Unsupported screens, bridge errors, stale state, and
   validation failures stop the applicable action or episode. They never widen
   authority to mouse, keyboard, stale data, or a different model backend.
6. **Isolated formal runs.** A benchmark episode MUST NOT modify the normal
   profile, normal saves, Steam configuration, or unrelated installed mods.
7. **Auditable execution.** State, legal actions, normalized commands, results,
   hashes, timings, and policy usage are recorded with explicit provenance.
8. **Empirical determinism.** Fixed seed is a test input, not proof of replay
   parity. Repeated execution must establish the actual parity boundary.
9. **Backend independence.** Scripted, solver, AGY, OpenCode2, direct API, and
   future policies use the same H1 action and validation path.
10. **Bounded model cost.** Stable-state deduplication, per-room sessions,
    compact deltas, and action batching prevent one model call per animation or
    per unchanged observation.

## 4. Scope

### 4.1 Initial supported scope

H1 MUST initially support:

- the locally installed Steam build of Slay the Spire 1;
- Windows 64-bit execution;
- ModTheSpire and BaseMod;
- a CommunicationMod-compatible Java bridge;
- vanilla content only;
- Ironclad;
- Ascension 0;
- seeded and unseeded runs;
- Neow choice, map choice, combat, potions, card rewards, combat rewards,
  events, shops, rest sites, treasures, boss rewards, game over, and victory;
- one serial native game process per formal episode;
- fixture-based offline development without a running game;
- player-visible and omniscient-debug observation profiles;
- structured replay and repeated-seed parity comparison.

### 4.2 Later compatible scope

The architecture MUST leave room for:

- Silent, Defect, and Watcher;
- Ascension 1 through 20;
- Act 4 and Heart-specific completion criteria;
- Daily/custom runs;
- supported content mods through dynamic catalogs;
- multiple policy classes and benchmark suites;
- parallel isolated processes after serial isolation is proven;
- an MCP adapter at the outer boundary;
- a deterministic tactical combat solver;
- remote model APIs.

These are not H1 acceptance requirements unless promoted by a later spec
revision.

## 5. Non-goals

The initial project does not attempt to:

- reimplement Slay the Spire as an independent simulator;
- modify or redistribute the game's executable, `desktop-1.0.jar`, art, audio,
  localization, or other proprietary content;
- guarantee headless native execution;
- automate the ModTheSpire launcher through OS-level UI input;
- expose hidden draw order, RNG state, unrevealed rewards, unrevealed event
  outcomes, or future shop contents to a formal player-visible policy;
- make raw `KEY`, `CLICK`, or arbitrary CommunicationMod commands available to
  a model;
- treat screenshots as the authoritative state source;
- require or store private model chain-of-thought;
- silently continue through an unsupported screen;
- claim cross-machine determinism from hashes alone;
- support gameplay content mods in the first formal benchmark;
- change, migrate, or commit the operator's normal save progress.

## 6. Verified local target baseline

The following target was inspected on 2026-09-04. It is the initial local
development baseline, not a promise that future Steam updates are compatible.

### 6.1 Game

- Steam app ID: `646570`
- Steam manifest build ID: `10180494`
- Installation root: `F:\SteamLibrary\steamapps\common\SlayTheSpire`
- `desktop-1.0.jar` size: `365086855` bytes
- `desktop-1.0.jar` SHA-256:
  `CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673`
- `SlayTheSpire.exe` size: `372736` bytes
- `SlayTheSpire.exe` SHA-256:
  `44B8EACFD3843A8666E980DC9C71A50A069EF58610FB134464D1B606434C9603`
- Bundled runtime: Java 8, `1.8.0_144-b01`

### 6.2 Installed framework mods

- ModTheSpire `3.30.3`
  - Workshop item: `1605060445`
  - SHA-256:
    `541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604`
- BaseMod `5.56.0`
  - Workshop item: `1605833019`
  - SHA-256:
    `C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF`
- StSLib `2.12.0`
  - Workshop item: `1609158507`
  - SHA-256:
    `B71A4934C9EB6C020799F5418B0BEC5E5957879F9A0F8B4F7CE80288F456FF62`
  - StSLib is installed but MUST be disabled for the initial vanilla H1 run
    unless the bridge build proves it requires StSLib.

CommunicationMod is not currently installed. Its public Workshop item is not a
reliable installation dependency. The project MUST pin source provenance and
build its accepted bridge JAR reproducibly.

### 6.3 Target gate

Before a native integration run, the launcher MUST verify at least:

- app ID;
- resolved install root;
- `desktop-1.0.jar` hash;
- ModTheSpire JAR hash and version;
- BaseMod JAR hash and version;
- bridge JAR hash and protocol version;
- Java runtime version;
- exact enabled mod set;
- normal profile/save fingerprint availability.

A mismatch MUST produce `ENVIRONMENT_MISMATCH` before any episode mutation.
Supporting a new target requires an explicit compatibility record and regression
run; a new Steam build MUST NOT be accepted solely because the game launches.

## 7. Terminology and authority layers

### 7.1 Native state

State held by the running game. This is the ultimate gameplay authority, but it
is not completely visible to the Harness.

### 7.2 Raw bridge export

The complete JSON document emitted by the accepted Java bridge for one stable
state. It may contain implementation identifiers or information that is not
appropriate for a player-visible policy.

The phrase `raw bridge export` MUST NOT be described as the complete native game
state.

### 7.3 Normalized exported state

A versioned, deterministic normalization of the raw bridge export. It removes
transport noise, normalizes types, assigns Harness-local stable handles, and
preserves all fields required for debugging and post-action verification.

### 7.4 Agent observation

The fairness-profile projection delivered to a policy. Formal results use the
`player_visible.v1` projection.

### 7.5 Legal-action snapshot

The exact set of discrete actions and parameterized action templates authorized
at one stable state. It is derived from normalized exported state plus native
availability and is bound to an observation hash.

### 7.6 Policy

Any component that chooses actions: scripted baseline, random baseline,
heuristic bot, tactical solver, LLM, hybrid controller, or human-supervised
command session.

### 7.7 Episode

One run from a fresh accepted reset to a terminal, truncated, failed, or closed
state. A formal episode owns one isolated native process.

### 7.8 Room session

The policy conversation scope for one combat or one non-combat decision room.
It is shorter than a complete game run.

## 8. Architecture

```text
Slay the Spire 1
  + ModTheSpire
  + BaseMod
  + StSHarnessBridge / pinned CommunicationMod-compatible bridge
            |
            | UTF-8 newline-delimited state and commands
            v
Private bridge worker / sidecar
  - protocol handshake
  - normalization and stable handles
  - observation projection
  - legal-action generation
  - action submission and verification
  - loopback public API
            |
            | framed JSON-RPC 2.0
            v
Episode controller
  - reset / step / replay / close
  - isolation and process ownership
  - audit and artifacts
  - policy-neutral transition contract
            |
            +--> scripted and solver policies
            +--> AGY adapter
            +--> OpenCode2 adapter
            +--> future API adapter
            +--> operator command center
```

The bridge worker and episode controller MAY run in one Python process in the
first implementation. Their interfaces MUST remain separable so fixture tests
can replace the native transport.

## 9. Reuse boundary with Kingdom Rush Harness

The implementation SHOULD port, with tests and project-specific renaming, the
following concepts and components from the current Kingdom Rush Harness:

- model backend result types;
- AGY and OpenCode2 model catalog/session adapters;
- provider-specific usage and latency accounting;
- response JSON extraction and one bounded format-repair path;
- request IDs and stale-response rejection;
- loopback-only public server and framed JSON-RPC;
- canonical document hashing and transition-chain audit;
- JSONL artifact organization;
- attachments with size and hash checks;
- command-center process lock, lifecycle, and watchdog concepts;
- passive-read versus explicit-mutation authority;
- model selection and thinking-variant discovery;
- explicit failure instead of backend fallback.

The implementation MUST NOT import `kr_harness` as a runtime dependency and
MUST NOT reuse the following domain behavior:

- Lua bridge code;
- tower, wave, power, level, or campaign-save actions;
- Kingdom Rush observation compactors or prompts;
- tower-development policy gates;
- Kingdom Rush rewards or scripted baselines;
- Steam app `246420` launch configuration;
- Kingdom Rush save formats and deployment paths.

The first Slay the Spire implementation SHOULD copy only selected generic
modules into the `sts_harness` namespace. A shared package MAY be extracted
after both Harnesses pass their own regression suites. The existing working
Kingdom Rush project MUST NOT be refactored merely to make the first Slay the
Spire milestone appear DRY.

## 10. Build and dependency policy

### 10.1 Java bridge

The accepted bridge MUST:

- compile to Java 8-compatible bytecode;
- build from pinned source with a checked-in Maven Wrapper or another pinned,
  reproducible wrapper;
- reference the local game, ModTheSpire, and BaseMod JARs through explicit
  local properties or environment variables;
- fail clearly when a required local JAR is absent or has an unexpected hash;
- embed its protocol version and source revision;
- contain a `ModTheSpire.json` manifest with exact dependencies;
- avoid bundling the game JAR, BaseMod, ModTheSpire, or proprietary assets;
- retain third-party license notices for reused MIT code.

The bridge build MUST NOT require a globally installed Maven command. The build
MAY use an isolated JDK 8 installed outside the repository. Credentials are not
bridge build inputs.

### 10.2 Python sidecar

The sidecar MUST support Python 3.10 or later and SHOULD use a project-local
virtual environment. Dependency versions MUST be recorded by a lock file before
formal H1 acceptance.

### 10.3 Deployment

Bridge deployment MUST:

1. resolve and verify the exact game installation;
2. prove whether a Slay the Spire/ModTheSpire Java process is running;
3. refuse replacement while an affected process is live;
4. modify only the named Harness bridge target;
5. preserve an existing different target through a bounded backup;
6. leave unrelated mods untouched;
7. verify the deployed JAR hash;
8. record source and target hashes without recording credentials;
9. avoid changing Steam launch options in the initial milestone.

The formal runner MUST also verify from startup logs or bridge capabilities that
only the approved gameplay-affecting mod set is active.

## 11. Runtime modes

### 11.1 `episode`

Formal isolated execution. One launcher-owned game process and one sidecar own
one run. This is the only mode permitted to produce benchmark results.

### 11.2 `live`

Human-supervised play against an operator-opened modded game. Passive refresh is
read-only. A conversational turn may mutate the game only when the operator
clearly requests an action or explicitly enables automatic play for the current
native run.

Live results MUST NOT be mixed with formal episode results.

### 11.3 `fixture`

No native game. Recorded raw exports and expected commands drive normalizers,
legal-action generation, policy prompts, UI, and replay verification.

### 11.4 `replay`

Either offline trace verification or live re-execution against a fresh matching
environment. The report MUST distinguish these modes.

## 12. Fairness profiles

### 12.1 `player_visible.v1`

This is the default and required profile for formal model comparison.

It MAY expose:

- character, ascension, act, floor, room type, current HP, maximum HP, gold,
  keys, and game score fields already visible to the player;
- the complete owned deck and visible per-card upgrades;
- relics and their visible counters;
- potion slots, visible potions, and their legal use/discard status;
- the currently visible map and reachable node choices;
- current hand, energy, block, turn, visible buffs/debuffs, and card costs for
  the current turn;
- draw-pile size and a sorted multiset of card identities available through the
  in-game pile viewer, without internal draw order;
- discard and exhaust contents available through the in-game viewers;
- monster identities, HP, block, visible powers, visible intent, visible damage
  and hit count, and targetability;
- current screen choices and text already presented to the player;
- card, relic, potion, power, and choice descriptions corresponding to visible
  objects;
- the current legal-action set.

It MUST hide or neutralize:

- internal draw-pile order;
- RNG objects, counters, stream state, or next random values;
- unrevealed rewards, potions, relics, cards, events, shop inventory, and event
  results;
- hidden monster move history unless the game visibly communicates it;
- implementation-only native object addresses;
- absolute filesystem paths;
- raw save content;
- raw card UUIDs when they convey no player-visible meaning;
- future rooms or encounters not visible on the current map;
- the run seed from the model payload by default.

The seed MAY be recorded in restricted episode metadata. A later benchmark
profile MAY explicitly expose it, but its results must be labeled separately.

### 12.2 `omniscient_debug.v1`

This profile MAY retain all bridge-exported fields for debugging, coverage, and
serializer development. It MUST be visibly labeled `non_benchmark=true` and
MUST NOT share a leaderboard or aggregate with player-visible runs.

### 12.3 Projection allowlist

The player-visible observation MUST be built from an explicit allowlist. It
MUST NOT be implemented as a raw-state blocklist because newly added bridge
fields could otherwise leak hidden information by default.

## 13. Identity model

Every document MUST distinguish:

- `episode_id`: unique formal or live run owner;
- `native_session_id`: one game-process bridge generation;
- `run_id`: one in-game run from Neow/start to terminal outcome;
- `act_id`: current act identity;
- `room_id`: current combat or non-combat room identity;
- `combat_id`: current combat identity when applicable;
- `state_seq`: monotonically increasing normalized stable-state sequence;
- `decision_id`: identifier for a distinct actionable stable state;
- `request_id`: controller or policy request identifier;
- `model_session_id`: backend-specific conversation identity.

A native process restart MUST change `native_session_id`. A new run in the same
process MUST change `run_id`. A room transition MUST change `room_id`. Pending
responses bound to an earlier identity MUST be rejected as stale.

### 13.1 Card instances

The agent-facing `card_instance_id` is an opaque, session-local Harness handle.
It MUST NOT expose Java object identity or a raw UUID.

The sidecar MUST retain an internal mapping to the bridge's current card
identity. For replay, each selected card action MUST also record a canonical
selector containing enough current-state semantics to resolve an equivalent
instance in a fresh run, such as:

- card ID;
- upgrade count;
- current zone;
- current cost and relevant per-turn flags;
- occurrence ordinal among semantically identical candidates.

If two instances are semantically interchangeable, either may satisfy replay.
If they differ in current cost, retained state, misc value, or another gameplay
field, the selector MUST distinguish them.

### 13.2 Monsters

The agent-facing `target_id` MUST remain stable for the lifetime of an encounter
and SHOULD derive from native monster ID plus a deterministic spawn ordinal.
Raw array index is retained internally but is not sufficient as the public
identity.

### 13.3 Choices and map nodes

Choice IDs MUST be scoped to `decision_id` and remain independent of display
language. A choice should include its ordinal, normalized semantic kind, and
display text. Map nodes MUST use stable act-local coordinates plus a Harness
node ID.

## 14. Observation contract

### 14.1 Top-level shape

An agent observation has the following conceptual form:

```json
{
  "schema_version": "sts-observation.v1",
  "fairness_profile": "player_visible.v1",
  "episode_id": "ep_...",
  "native_session_id": "native_...",
  "run_id": "run_...",
  "room_id": "room_...",
  "combat_id": "combat_...",
  "state_seq": 42,
  "decision_id": "decision_...",
  "ready_for_action": true,
  "decision_kind": "combat",
  "run": {},
  "map": {},
  "combat": {},
  "screen": {},
  "catalog_delta": {},
  "observation_hash": "sha256:..."
}
```

Absent scopes MUST be represented consistently as `null` or omitted according
to the schema; implementations MUST NOT alternate arbitrarily.

### 14.2 Run scope

The `run` object SHOULD include, where applicable:

- character ID and display name;
- ascension level;
- act and floor;
- room type;
- current and maximum HP;
- gold;
- keys;
- deck entries with counts and instance summaries;
- relics with visible counters;
- potions and empty slots;
- visible game score fields;
- terminal state and outcome;
- a versioned compact strategy memo in H2 only.

Integer game quantities MUST remain integers. The normalizer MUST reject NaN,
infinity, unexpected floating-point values, and integer overflow outside the
documented range.

### 14.3 Map scope

The `map` object MUST distinguish:

- nodes visible in the current act;
- the current node;
- directly reachable legal nodes;
- known node symbol/type;
- parent/child edges;
- boss identity only when the game visibly reveals it.

Only directly reachable nodes may appear as `choose_map_node` legal actions.

### 14.4 Combat scope

The `combat` object SHOULD include:

- turn number;
- current energy and maximum visible energy when applicable;
- player block and visible powers;
- current hand in display order with Harness instance IDs;
- draw-pile count and fair multiset summary;
- discard and exhaust contents;
- cards in limbo or card-in-play only when their state affects the next legal
  decision;
- monsters in stable encounter order with stable target IDs;
- visible intents, damage, hit count, HP, block, powers, targetability,
  half-dead/escaped status where relevant;
- current card-selection or targeting substate;
- end-turn availability.

The observation MUST distinguish base cost from current turn cost and MUST
preserve special costs such as X-cost using an explicit enum or documented
sentinel rather than an unexplained negative integer.

### 14.5 Screen scope

`decision_kind` MUST normalize native screens into at least:

- `main_menu`;
- `neow`;
- `combat`;
- `combat_reward`;
- `card_reward`;
- `map`;
- `event`;
- `shop`;
- `rest`;
- `treasure`;
- `boss_reward`;
- `grid_select`;
- `hand_select`;
- `game_over`;
- `victory`;
- `unsupported`.

The `screen` object MUST contain the text and choices necessary to understand
the current decision, plus cardinality constraints for multi-card selection.

An actionable native screen that cannot be normalized MUST become
`decision_kind="unsupported"`, set `ready_for_action=false` for automated
policies, emit an `UNSUPPORTED_SCREEN` event, and stop formal automation. It
MUST NOT generate a coordinate-click fallback.

### 14.6 Catalogs

Catalog entries MAY describe visible or owned:

- cards;
- relics;
- potions;
- player and monster powers;
- characters;
- screen actions.

Every entry MUST use stable game IDs as the semantic key and display names only
for presentation. Descriptions MUST come from the installed game/mod runtime or
another version-pinned local source, not an unversioned online wiki.

The first observation of a room or model session MAY include a complete
referenced catalog subset. Later observations SHOULD send only `catalog_delta`
for newly encountered or changed IDs.

## 15. Legal-action contract

### 15.1 Snapshot shape

```json
{
  "schema_version": "sts-legal-actions.v1",
  "episode_id": "ep_...",
  "native_session_id": "native_...",
  "run_id": "run_...",
  "decision_id": "decision_...",
  "state_seq": 42,
  "observation_hash": "sha256:...",
  "actions": [],
  "templates": [],
  "legal_actions_hash": "sha256:..."
}
```

Every discrete action MUST contain a unique `action_id`, an action `type`, a
submit-ready typed payload, and enough presentation metadata for a policy or UI
to understand it.

Parameterized actions MUST list their candidate IDs and exact cardinality or
resource constraints. The validator MUST reject values not represented by the
current template.

### 15.2 Common submission envelope

```json
{
  "schema_version": "sts-action-batch.v1",
  "request_id": "req_...",
  "episode_id": "ep_...",
  "native_session_id": "native_...",
  "run_id": "run_...",
  "decision_id": "decision_...",
  "expected_observation_hash": "sha256:...",
  "expected_legal_actions_hash": "sha256:...",
  "stop_on_failure": true,
  "actions": []
}
```

Unknown top-level or action fields MUST be rejected. The protocol MUST NOT
silently coerce strings to numbers, truncate arrays, or accept ambiguous IDs.

### 15.3 Initial action types

#### `start_run`

Parameters:

- `character_id`;
- `ascension`;
- optional seed in the native accepted textual representation.

Available only from an accepted main-menu state. Initial H1 accepts only
`IRONCLAD` and ascension `0` unless a later capability explicitly widens it.

#### `play_card`

Parameters:

- `card_instance_id`;
- `target_id` when required;
- the current discrete `action_id` when enumerated.

The validator MUST confirm that the card is still in hand, playable, affordable
under current native rules, and supplied with exactly one legal target when
required. The sidecar resolves the current CommunicationMod hand and target
indices only after this validation.

#### `end_turn`

No parameters. Legal only when the native end-turn action is currently
available and no unresolved modal selection blocks it.

#### `use_potion`

Parameters:

- `potion_slot_id`;
- `target_id` when required.

#### `discard_potion`

Parameter: `potion_slot_id`.

Use and discard are separate legal actions. A full potion inventory and a
reward potion MUST be represented explicitly so the policy can discard, skip,
or take it without relying on a missing native state change.

#### `choose_option`

Parameter: `choice_id`. Used for Neow, events, simple rewards, treasure, boss
relics, and other discrete screens. Display name alone is never sufficient.

#### `select_cards`

Parameters:

- `selection_template_id`;
- ordered or unordered `card_instance_ids` as declared by the template;
- explicit `confirm=true` where the native flow requires confirmation.

The template MUST declare minimum, maximum, exact-count, any-number, duplicate,
cancel, and upgrade/transform/remove semantics. The bridge SHOULD implement the
selection atomically rather than depending on unsupported native unselection.

#### `choose_map_node`

Parameter: `map_node_id`. The node MUST be a current child of the native player
position and appear in the current legal-action snapshot.

#### `proceed`

No parameters. Represents an available native proceed/confirm flow that does
not require a semantic choice.

#### `return_or_skip`

No parameters unless the legal snapshot distinguishes multiple return-like
actions. It MUST state whether the semantic result is skip, cancel, leave, or
return.

#### `buy_item`

Parameter: `shop_item_id`. The item must still be present, affordable, and
permitted by inventory constraints.

#### `remove_card`

Parameter: `card_instance_id`. Available only through a current shop or event
removal template and subject to current cost and selection constraints.

#### `rest_site_action`

Parameter: `rest_action_id`, for example rest, smith, lift, dig, recall, or
another currently visible native action. The Harness MUST enumerate only
actions actually unlocked in current native state.

### 15.4 Operator-only actions

The following MUST NOT appear in model-facing legal actions:

- arbitrary raw command;
- `KEY`;
- `CLICK`;
- unconstrained `WAIT`;
- debug state mutation;
- grant gold, HP, relics, cards, or rewards;
- forced room or encounter selection;
- save editing;
- process termination;
- run abandonment unless a benchmark explicitly authorizes it.

Operator-only debug commands must use a separate capability and audit namespace.

## 16. Batch semantics

A policy MAY submit multiple immediate actions, primarily to express one combat
turn plan. A batch is not a native atomic transaction.

The executor MUST:

1. validate the batch envelope against the captured observation and legal-action
   hashes;
2. validate the first action against the latest native stable state;
3. submit exactly one native command;
4. wait for and normalize the resulting stable state or explicit error;
5. verify the action result;
6. regenerate legal actions;
7. re-resolve stable handles and revalidate the next action;
8. stop on terminal state, room change, unexpected modal choice, stale identity,
   timeout, unsupported screen, or invalid next action.

`stop_on_failure` MUST be `true` for model submissions in v1. Earlier successful
actions remain successful and audited. The result MUST be labeled
`PARTIAL_SUCCESS` rather than rolled back or reported as a full failure.

The Harness MAY preflight deterministic constraints such as current shop budget
or selection cardinality, but it MUST NOT assume future card draws, generated
cards, changing energy, cost mutations, target survival, or random effects.

## 17. Stable-state and decision semantics

The raw bridge determines when the native game is stable enough to accept a
command. The sidecar adds a second decision gate.

A state is policy-actionable only when:

- the bridge reports readiness;
- the native session and run identity are current;
- normalization succeeded;
- the decision kind is supported;
- at least one model-facing legal action exists;
- no previous native command remains unresolved;
- the save and environment guards remain valid.

The sidecar MUST deduplicate identical actionable states. Repeated raw exports
with the same decision identity, observation hash, and legal-action hash MUST
not trigger additional model turns.

A new model decision may be triggered by:

- a new combat turn;
- a hand or modal selection that invalidates the remaining action plan;
- a new map, reward, event, shop, rest, treasure, or boss-reward choice;
- explicit operator input in live mode;
- explicit policy retry after one recoverable format error.

Animations, frame counts, log output, unchanged polling observations, and
non-actionable state changes MUST NOT trigger a model call.

## 18. Private bridge protocol

### 18.1 Baseline compatibility

The initial adapter may use the CommunicationMod convention:

- the Java mod launches one external process;
- the process writes `ready\n` to stdout within the configured handshake
  deadline;
- the mod writes one UTF-8 JSON state or error document per line to the
  process's stdin;
- the process writes one native command line to stdout;
- the game responds after it reaches a stable state.

### 18.2 Stream purity

The child process stdout is protocol-only. It MUST contain only the required
handshake and native commands. Logs, progress, tracebacks, model output, and
debug text MUST go to stderr or an explicit file.

No credential or model token may appear in either stream.

### 18.3 Limits and parsing

- Encoding: strict UTF-8.
- Message termination: LF; CRLF is accepted and normalized on input.
- Maximum raw state line: `16 MiB` in v1.
- Duplicate JSON object keys: rejected.
- Invalid JSON: `BRIDGE_PROTOCOL_ERROR`.
- Unexpected non-JSON bridge line after handshake: protocol error unless the
  pinned bridge contract explicitly classifies it as a log prefix.
- The sidecar MUST continuously drain stderr to avoid child-process deadlock.

### 18.4 Lifecycle failure

If the controller becomes unavailable, the bridge worker MUST NOT invent a
gameplay command or fall back to keyboard/mouse input. Formal episode mode fails
the episode. Live mode surfaces the disconnection and leaves control with the
operator.

## 19. Public sidecar protocol

The public sidecar binds only to loopback. It uses UTF-8 JSON-RPC 2.0 framed as:

```text
[u32 big-endian payload length][JSON payload bytes]
```

The maximum frame size is `4 MiB`. Screenshots and other large media are passed
as hash-verified local artifacts, not inline base64 frames.

All mutating requests MUST carry or resolve the expected episode/session/run
identity. A per-run controller nonce SHOULD be supplied through an
ACL-restricted descriptor and MUST NOT be exposed to a model prompt or log.

### 19.1 Low-level methods

The sidecar SHOULD expose:

- `bridge.status`;
- `ping`;
- `capabilities`;
- `observe`;
- `get_legal_actions`;
- `submit_action`;
- `capture_frame` when implemented;
- `quit` for an owned isolated process;
- namespaced read-only debug methods in non-benchmark mode.

Raw CommunicationMod command submission MUST NOT be part of the normal public
API.

## 20. Episode API

### 20.1 `env.reset`

Conceptual request:

```json
{
  "character_id": "IRONCLAD",
  "ascension": 0,
  "seed": "OPTIONAL_NATIVE_SEED",
  "fairness_profile": "player_visible.v1",
  "policy_mode": "scripted",
  "max_episode_decisions": 10000,
  "max_episode_seconds": 14400
}
```

Formal `env.reset` MUST:

1. validate the target environment;
2. create a unique artifact and profile directory;
3. fingerprint normal saves and installation state;
4. launch or bind exactly one owned game process;
5. verify the exact bridge and enabled mod set;
6. start a fresh run with the accepted configuration;
7. wait for the first supported stable decision;
8. return the initial transition.

A second formal reset on the same native process is not accepted in v1. The
caller must close the episode and create a fresh process.

### 20.2 `env.observe`

Read-only. Returns the latest normalized transition snapshot. It MUST NOT send a
native state-changing command or start a model turn.

### 20.3 `env.step`

Accepts one action batch and returns the next transition after verified
execution or failure. It MUST never claim success from command acceptance alone.

### 20.4 `env.advance_until_decision`

Waits for the next distinct actionable stable state without asking a model to
act. It MAY submit a narrowly defined no-op/wait primitive only when the pinned
bridge requires it to finish native animations and the operation is documented
as non-mutating gameplay progression.

### 20.5 `env.replay`

Returns trace metadata, normalized transitions, actions, hashes, metrics, and
the final chain hash. It MAY optionally start a separate live replay execution
through an explicit mode.

### 20.6 `env.close`

Stops only episode-owned processes, finalizes artifacts, and verifies post-run
guards. It is idempotent. It MUST NOT kill unrelated Java, Steam, Python,
OpenCode, or AGY processes by name.

## 21. Transition result

Every reset or step returns a document conceptually shaped as:

```json
{
  "schema_version": "sts-transition.v1",
  "episode_id": "ep_...",
  "transition_index": 12,
  "observation": {},
  "legal_actions": {},
  "events": [],
  "submitted_batch": null,
  "action_results": [],
  "reward": {
    "schema_version": "sts-reward-vector.v1",
    "terminal": 0,
    "floor_delta": 0,
    "score_delta": 0,
    "hp_delta": -3
  },
  "terminal": false,
  "truncated": false,
  "outcome": null,
  "metrics": {},
  "hashes": {
    "raw_export_hash": "sha256:...",
    "observation_hash": "sha256:...",
    "legal_actions_hash": "sha256:...",
    "transition_hash": "sha256:...",
    "chain_hash": "sha256:..."
  }
}
```

The transition must make partial batch execution explicit. `action_results`
contains one entry per attempted action and records all unattempted trailing
actions with a precise skip reason.

## 22. Action verification

An action is successful only when all applicable checks pass:

- the native bridge accepted the command;
- a new stable export or explicit terminal result arrived;
- the expected run and room identities remain coherent;
- the post-state demonstrates the intended semantic transition;
- no bridge error contradicts success.

Examples:

- `play_card`: the selected card left the hand or entered the documented
  in-play/limbo state, energy/cost semantics are coherent, and a modal follow-up
  is represented when generated;
- `end_turn`: turn ownership advanced or the combat terminated;
- `choose_map_node`: the selected node became current or the corresponding room
  transition began;
- `buy_item`: gold and inventory changed consistently and the item disappeared
  from the current shop;
- `use_potion`: the potion slot changed and the native effect or transition is
  observable;
- `choose_option`: the decision identity changed or an explicit native result
  acknowledged the choice.

When the exported state cannot prove an action's semantic effect, the result is
`ACTION_UNVERIFIED`, not success. The bridge may need to add an explicit native
action-result event for that path.

## 23. Outcomes and truncation

Normalized outcomes include at least:

- `VICTORY_ACT3`;
- `VICTORY_ACT4`;
- `DEFEAT_COMBAT`;
- `DEFEAT_EVENT` when distinguishable;
- `ABANDONED`;
- `TRUNCATED_DECISION_LIMIT`;
- `TRUNCATED_TIME_LIMIT`;
- `FAILED_UNSUPPORTED_SCREEN`;
- `FAILED_BRIDGE`;
- `FAILED_ENVIRONMENT_GUARD`;
- `FAILED_PROCESS_EXIT`;
- `FAILED_POLICY`.

Formal Ironclad A0 H1 completion initially treats the native Act 3 victory state
as success. Act 4 and Heart completion are separate later benchmark targets.

An interrupted, crashed, unsupported, or manually completed run MUST NOT be
reported as a policy victory.

## 24. Rewards and metrics

### 24.1 Reward vector

H1 reports a versioned reward vector but does not require a single scalar RL
reward. The initial vector SHOULD include:

- terminal result: `1`, `0`, or `-1`;
- floor delta;
- visible score delta when available;
- player HP delta;
- max HP delta;
- gold delta;
- optional combat damage taken;
- optional elite/boss completion markers.

A scalar composite MAY be added only with a separately versioned scoring policy.
Changing weights creates a new scoring version and MUST NOT rewrite historical
results.

### 24.2 Episode metrics

Every formal run records at least:

- character, ascension, seed, act, floor, room, and native score;
- outcome and terminal/truncation reason;
- starting, minimum, and final HP;
- HP lost by combat and non-combat source when available;
- gold gained/spent;
- cards added, removed, transformed, and upgraded;
- relics and potions acquired, used, discarded, and skipped;
- combat turns and rooms completed;
- actions attempted, accepted, rejected, partially executed, and unverified;
- unsupported-screen count;
- state/decision count and deduplication count;
- process and episode wall time;
- model call count and repair count when applicable;
- model input, cache-read, reasoning, visible-output, and total token fields when
  the backend provides them;
- first-token, generation, and end-to-end latency when available;
- replay parity status and first divergence when applicable.

Missing provider metrics MUST be represented as unavailable, not zero.

## 25. Canonicalization and hashes

### 25.1 Canonical bytes

Hashed documents MUST use one implementation-independent canonical encoding.
The initial implementation may use canonical UTF-8 JSON with all of the
following rules:

- object keys sorted by Unicode code point;
- no insignificant whitespace;
- UTF-8 without BOM;
- JSON string escapes normalized consistently;
- integers encoded in base 10 without leading zeros;
- floating-point values prohibited in hashed protocol state;
- duplicate keys rejected before canonicalization;
- semantic sets sorted by documented stable keys;
- semantic sequences retain their meaningful order;
- absent, `null`, and empty values are not interchangeable.

If a later version adopts canonical binary encoding, it MUST increment the hash
schema version. A hash without its schema version is invalid.

### 25.2 Hash scopes

- `raw_export_hash`: normalized exported state, including debug-only fields but
  excluding transport timestamps and raw nondeterministic identities that have
  stable aliases;
- `observation_hash`: exact agent observation excluding its own hash field;
- `legal_actions_hash`: exact legal-action document excluding its own hash;
- `transition_hash`: transition index, pre/post hashes, normalized submitted
  actions, action results, terminal flags, and environment fingerprint ID;
- `chain_hash`: previous chain hash plus current transition hash.

`observation_hash` is deliberately **run-local**. The exact observation includes
`episode_id`, `native_session_id`, `run_id`, room/combat/decision identities,
and run-local stable aliases for native objects. Therefore two executions with
the same seed and semantically identical game state will normally have different
`observation_hash` values. This is correct: the hash is an integrity and stale-
decision precondition inside one episode, not a cross-run determinism claim.

Live replay MUST NOT compare `observation_hash` directly across native
executions. H1-B defines a separately versioned replay-checkpoint projection
that removes or deterministically rebases run-scoped identities while retaining
the semantic player-visible state required by the parity contract. Implementations
that predate that projection may compare explicit normalized semantic fields,
but MUST NOT report parity from cross-run `observation_hash` equality. Because
`legal_actions_hash`, `transition_hash`, and `chain_hash` incorporate run-local
documents or identities, they are trace-integrity hashes rather than direct
cross-run checkpoint hashes as well.

`sts-replay-checkpoint.v1` implements that contract as follows:

- episode, native-session, run, room, combat, state, decision, action, choice,
  card-instance, target, map-node, reward, shop-item, selection-template, and
  native-index identities are removed or represented by semantic selectors;
- hand order and hand/card-in-play dynamic values remain strict because they are
  immediately actionable;
- draw, discard, exhaust, and limbo collections are semantic multisets;
- in those inactive combat zones only, cached `damage`, `block`,
  `cost_for_turn`, `is_playable`, `free_to_play_once`, and `retain` values are
  excluded because native code may retain a target/power-adjusted cache until
  the card is drawn and recalculated;
- card ownership, zone, intrinsic structure, permanent upgrade/misc state,
  counts, HP, gold, powers, monster state and intent, screen state, map state,
  and canonical legal-action selectors remain strict.

The omitted inactive-zone caches remain present in the exact observation and
`observation_hash`. A replay divergence is not waived ad hoc: every narrowing
rule is versioned and embedded in the checkpoint's `projection_contract`.

Wall-clock timestamps, UI animation counters, log line numbers, process IDs,
model prose, and provider latency MUST NOT enter native-state parity hashes.
They remain in the audit trail.

## 26. Replay

### 26.1 Offline verification

The verifier MUST independently recompute every canonical document hash,
transition hash, and chain hash from trace artifacts. It MUST detect missing,
duplicated, reordered, or modified records.

### 26.2 Live re-execution

Live replay starts a fresh isolated process with the exact recorded environment
fingerprint and run configuration. At each decision it resolves the recorded
canonical action selector against current legal actions and compares normalized
checkpoints.

The comparison MUST distinguish:

- `REPLAY_VALID`: offline chain is internally valid;
- `REPLAY_PARITY`: live re-execution matched all required checkpoints;
- `REPLAY_INVALID`: trace structure or hashes are invalid;
- `REPLAY_ENVIRONMENT_MISMATCH`: required game, mod, bridge, JVM, schema, or
  config fingerprint differs;
- `REPLAY_ACTION_UNRESOLVABLE`: an equivalent recorded action cannot be mapped;
- `REPLAY_DIVERGED`: environment matched but a required checkpoint differed.

A divergence report MUST include:

- first divergent transition index;
- room, combat, turn, and decision kind;
- recorded and replayed normalized action;
- recorded and replayed hashes;
- a bounded structural field diff;
- relevant environment fingerprint fields.

Checksums detect and locate divergence. They do not independently prove that
all hidden native state or every platform behaves identically.

## 27. Save and profile isolation

### 27.1 Normal data boundary

The launcher MUST identify and fingerprint every normal path the accepted stack
could modify, including at least:

- the game's `preferences` directory;
- the game's `saves` directory;
- `betaPreferences` when present;
- ModTheSpire and bridge configuration under the user's local application data;
- the Steam manifest and applicable user launch configuration;
- installed mod targets managed by the deployment tool.

The exact list must be proven through a compatibility probe. Assumed paths are
not sufficient.

### 27.2 Formal profile

Each formal episode uses a unique profile root. It MUST contain only the files
required for that episode and MUST never be selected by a fallback path when
its configuration is incomplete.

The launcher MUST verify that the game and each mod actually write to the
isolated locations. Environment variables, working directory, JVM properties,
or file redirection mechanisms are accepted only after a real write-path test.

### 27.3 Guards

- Capture pre-run normal-data metadata and content hashes.
- Refuse the episode if the pre-run guard cannot be established.
- Capture post-run fingerprints after owned processes exit.
- Any unexpected normal-data change makes the run invalid and produces
  `SAVE_GUARD_FAILED`.
- The Harness MUST NOT automatically copy isolated progress back to the normal
  profile.
- A future explicit commit workflow requires a separate spec and operator
  authorization.
- On the accepted Windows/Steam target, a formal launcher MUST refuse to start
  while the interactive `steam.exe` client is active because it is an
  independent writer of guarded user `localconfig.vdf`. The launcher MUST NOT
  terminate Steam automatically. The background `SteamService.exe` alone is not
  the interactive client and is not a rejection condition.

## 28. Process ownership and lifecycle

### 28.1 Episode state machine

```text
CREATED
  -> PREFLIGHTED
  -> STARTING_GAME
  -> WAITING_FOR_BRIDGE
  -> READY
  -> IN_RUN
  -> TERMINAL | FAILED | TRUNCATED
  -> CLOSING
  -> CLOSED
```

Invalid transitions are errors. Terminal outcome and infrastructure failure are
separate fields.

### 28.2 Ownership

The launcher records exact owned process IDs, executable paths, creation times,
and command-line fingerprints. Cleanup may target only those owned processes or
their verified descendant chain.

It MUST NOT terminate processes by broad names such as `java.exe`,
`SlayTheSpire.exe`, `python.exe`, `steam.exe`, `opencode2`, or `agy`.

### 28.3 Deadlines

Separate deadlines are required for:

- native process startup;
- bridge `ready` handshake;
- first stable state;
- individual native command completion;
- model inactivity;
- model absolute turn duration;
- full episode duration;
- graceful close.

One timeout MUST NOT be reused to disguise failure in another phase. Timeout
errors include the phase and last verified state.

## 29. H2 model adapter

### 29.1 Backend interface

Every backend implements one policy-neutral turn contract and returns:

- backend and full model reference;
- backend session ID;
- raw visible response text;
- extracted structured response;
- provider events required for audit;
- usage categories when available;
- latency markers when available;
- explicit error type and message;
- whether a bounded format repair was attempted.

Backends MUST NOT directly invoke native game commands.

### 29.2 Session scope

The default H2 scope is one model session per room:

- one combat session persists across all player turns in that combat;
- one non-combat room session persists through its reward/selection chain;
- a room identity change closes the active model session;
- an act change forces a complete new baseline;
- a new native run invalidates every old model session and pending response.

A configurable run- or act-scoped session MAY be evaluated later but must be
labeled with its scope.

### 29.3 Run memory

Cross-room strategy is carried only through a bounded, structured
`sts-run-memory.v1` document, for example:

```json
{
  "deck_plan": "strength scaling with selective exhaust",
  "upgrade_priorities": ["Bash", "Inflame"],
  "path_risk": "medium",
  "desired_resources": ["sustain", "area damage"],
  "avoid": ["low-impact common attacks"]
}
```

The memory has a strict byte limit, is visible in the audit, and is treated as
policy advice rather than native truth. Current native state always overrides
it. The model may propose a replacement only in its structured response; the
controller validates schema and size before storing it.

### 29.4 Prompt composition

The first turn in a room receives:

- policy and fairness rules;
- current run summary;
- bounded run memory;
- complete current room observation;
- current legal actions;
- referenced catalog entries needed to interpret visible objects;
- action response schema;
- a statement that prose does not execute actions.

Later turns receive:

- current dynamic state;
- state and legal-action hashes;
- changes since the room baseline;
- newly referenced catalog entries;
- previous action results relevant to the current decision.

Unchanged full deck, relic, map, and catalog documents SHOULD be represented by
hash-keyed session baseline references rather than repeated verbatim.

The prompt MUST NOT include raw bridge state, hidden fields, save paths,
controller nonce, credentials, unrestricted trace paths, or unrelated workspace
files.

### 29.5 Model response

```json
{
  "schema_version": "sts-model-response.v1",
  "request_id": "req_...",
  "expected_observation_hash": "sha256:...",
  "reply": "Short operator-visible explanation.",
  "run_memory": null,
  "actions": []
}
```

The model is never required to reveal private chain-of-thought. `reply` should
be a concise, auditable rationale. Only validated `actions` reach H1.

One bounded repair turn MAY be attempted when otherwise successful model output
contains recoverable formatting errors. Repair MUST reuse the same request ID,
state hashes, and model session and MUST NOT receive a newer state implicitly.

### 29.6 Model tool boundary

A formal player-visible policy MUST NOT have filesystem or tool access that can
read:

- raw state traces;
- normal or isolated save files;
- seed-bearing metadata outside the permitted prompt;
- game memory;
- future reward or encounter data;
- another policy's output;
- unrestricted web seed databases when the benchmark declares closed-book
  play.

Permitted tools and files are part of the benchmark fingerprint.

## 30. Policy modes and benchmark separation

At least the following policy labels are reserved:

- `scripted_random_legal`;
- `scripted_greedy`;
- `tactical_solver`;
- `llm`;
- `hybrid_llm_solver`;
- `human_supervised`.

`llm` means the model selects combat and strategic actions without an external
tactical solver choosing on its behalf. `hybrid_llm_solver` means the tactical
solver may choose combat actions while the LLM handles strategic decisions.

Results from these modes MUST remain separate. A solver result must never be
presented as pure model performance.

The baseline interface uses the same observations and legal actions as the LLM
unless a benchmark explicitly declares a different fairness profile.

### 30.1 H1-C scripted-baseline boundary

The initial H1-C scripted subset consists of exactly two policy modes:

- `scripted_random_legal`;
- `scripted_greedy`.

Each policy receives only the exact `sts-observation.v1` and
`sts-legal-actions.v1` documents returned by the public H1 API. It MUST NOT read
raw-state artifacts, native commands, save files, process memory, hidden seed
state, another policy's output, or future trace records. Policy-private state is
allowed only when it is derived from prior player-visible inputs and the
policy's own prior selections, and it must be represented in the policy audit.

Every scripted policy has a versioned descriptor containing its policy ID,
policy version, fairness profile, determinism contract, and optional policy
seed. A change to action ranking, candidate ordering, random selection, or
policy-private state semantics requires a new policy version. The H1-B coverage
driver and its post-coverage terminal strategy are not a baseline and MUST NOT
be included in H1-C results.

### 30.2 Random-legal policy

`scripted_random_legal` chooses exactly one member of the current legal-action
set without action-type filtering. Terminal states require no selection. Its
pseudorandom draw is reproducible from a separately recorded policy seed,
zero-based policy decision index, and the canonical semantic candidate set; it
does not receive or derive randomness from hidden native state.

Candidates are represented only by action type plus
`sts-action-selector.v1`, sorted by canonical UTF-8 JSON bytes. Duplicate
semantic candidates are an error. The initial implementation maps a SHA-256
draw into the candidate range with rejection sampling so modulo bias does not
become an undocumented policy rule. The draw digest, retry counter, candidate
set hash, selected canonical index, and selected semantic selector are retained
for independent verification.

### 30.3 Deterministic greedy policy

`scripted_greedy` uses a versioned, deterministic set of simple player-visible
heuristics for combat, pathing, rewards, shops, rest sites, events, selections,
potions, and boss relics. It may inspect only fields in the two public policy
documents. It MUST NOT query the bridge or native game directly.

All candidate rankings use integer values. Equal-ranked candidates are resolved
by the canonical semantic candidate order, never by run-local `action_id`,
card-instance ID, decision ID, or native collection index. The policy continues
attempting ordinary play until the native game reaches victory or defeat, or an
explicit suite limit truncates it. It MUST NOT inherit H1-B's deliberate Act 2
`end_turn` terminal strategy.

### 30.4 Scripted suite and result artifacts

A formal scripted suite uses `sts-scripted-baseline-suite.v1` and records:

- a stable suite ID and canonical configuration hash;
- exact character, ascension, fairness profile, native seed matrix, policy IDs,
  policy versions, and policy seeds;
- per-episode decision and wall-time limits;
- one isolated native episode per policy/seed case, executed serially;
- the environment fingerprint and exact run directory for every episode;
- one append-only `sts-scripted-policy-decision.v1` audit per policy choice;
- per-policy episode results and per-policy integer/rational aggregates.

The suite MUST retain terminal, truncated, failed, and not-run cases rather than
dropping them. Infrastructure status, policy outcome, and native outcome are
separate fields. It MUST NOT publish a blended score across policy modes.
Provider/model usage fields remain explicitly unavailable for both scripted
policies.

The policy-decision audit binds the pre-action observation/legal-action hashes,
replay-checkpoint hash, canonical candidate-set hash, selected semantic action,
selection evidence, policy-state digests, decision hash, and chained decision
hash. An independent verifier reruns the policy over the recorded public inputs
and recomputes the complete decision chain; the policy's own summary is not
sufficient evidence.

## 31. Operator command center

The future H2 command center SHOULD reuse the established Harness control shell
while presenting Slay the Spire-specific state.

It SHOULD display:

- connection, native session, run, room, and decision identity;
- character, ascension, act, floor, room, HP, max HP, gold, deck size, relic
  count, and potions;
- in combat: turn, energy, hand, pile counts, player powers, monsters, intents,
  HP, block, and powers;
- current screen choices and legal actions;
- active backend, model, thinking variant, and model session;
- latest model reply and exact validated action results;
- per-turn and cumulative usage and latency;
- audit events, errors, replay status, and save guards.

Passive refresh MUST call read-only methods only. Historical trace selection
MUST never rebind action authority to an old run. A model response from a prior
run, room, or decision cannot be executed.

In live mode, a normal informational message is conversation-only. Mutation
requires either a clear current-turn operation request or an explicit automatic
play switch bound to the current `run_id`. Changing backend or model remains an
operator action; no failure may trigger automatic backend substitution.

## 32. Screenshot contract

Native frame capture is optional for the first H1 protocol milestone but should
be supported before H2 visual delivery is considered complete.

A captured frame MUST:

- originate from the current native game process;
- be captured after the corresponding stable state;
- be stored under the current episode artifact root;
- pass size, format, dimension, and SHA-256 checks;
- record associated state sequence and observation hash;
- contain no unrelated desktop content when native capture is available;
- remain auxiliary to structured state.

Capture failure does not widen action authority. A policy turn may continue with
structured state only when its benchmark allows that fallback and the fallback
is recorded. Otherwise the turn fails explicitly.

## 33. Artifacts and audit

Each episode writes one unique directory:

```text
artifacts/runs/<episode-id>/
  environment.json
  config.json
  bridge-events.jsonl
  transitions.jsonl
  actions.jsonl
  policy-events.jsonl
  usage.json
  replay.json
  summary.json
  frames/
  logs/
```

### 33.1 `environment.json`

Contains the game, mod, bridge, JVM, Harness, schema, fairness, policy-tool, and
configuration fingerprint. It contains no credential values.

### 33.2 `transitions.jsonl`

Contains normalized transition records and hashes. Raw omniscient state, if
retained, MUST be stored separately and marked non-benchmark.

### 33.3 `actions.jsonl`

Contains submitted action batches, per-action validation, resolved native
commands, action results, and partial-success details. Raw native indices may be
audited here but are never the policy-facing identity.

### 33.4 `policy-events.jsonl`

Contains prompt metadata, response metadata, structured model output, backend
events, errors, repairs, and usage. Credentials and hidden-state files are
excluded.

### 33.5 `summary.json`

Contains final outcome, acceptance-relevant counts, guard results, process
cleanup results, and links to trace files. An incomplete episode cannot write a
success summary.

Artifact writes SHOULD be append-only or atomic. A crash must leave enough
information to identify the last complete transition without treating a
partial JSON line as valid.

## 34. Error model

Errors use stable machine-readable codes and human-readable messages. Initial
codes include:

- `ENVIRONMENT_MISMATCH`;
- `UNAPPROVED_MOD_SET`;
- `SAVE_GUARD_FAILED`;
- `PROCESS_OWNERSHIP_ERROR`;
- `BRIDGE_NOT_READY`;
- `BRIDGE_PROTOCOL_ERROR`;
- `BRIDGE_TIMEOUT`;
- `NATIVE_PROCESS_EXITED`;
- `NORMALIZATION_ERROR`;
- `UNSUPPORTED_SCREEN`;
- `STALE_NATIVE_SESSION`;
- `STALE_RUN`;
- `STALE_ROOM`;
- `STALE_DECISION`;
- `STALE_OBSERVATION`;
- `LEGAL_ACTIONS_CHANGED`;
- `ACTION_SCHEMA_ERROR`;
- `ACTION_NOT_LEGAL`;
- `ACTION_PRECONDITION_FAILED`;
- `ACTION_UNVERIFIED`;
- `ACTION_PARTIAL_SUCCESS`;
- `MODEL_CATALOG_ERROR`;
- `MODEL_SESSION_ERROR`;
- `MODEL_TIMEOUT`;
- `MODEL_FORMAT_ERROR`;
- `MODEL_PROVIDER_ERROR`;
- `REPLAY_INVALID`;
- `REPLAY_ENVIRONMENT_MISMATCH`;
- `REPLAY_ACTION_UNRESOLVABLE`;
- `REPLAY_DIVERGED`.

Errors MUST preserve the most recent verified identities and hashes. They MUST
NOT include credentials, raw authorization headers, refresh tokens, or complete
unbounded provider payloads.

## 35. Performance and resource limits

Initial defaults:

- public JSON-RPC frame: `4 MiB` maximum;
- private raw bridge line: `16 MiB` maximum;
- image attachment: `20 MiB` maximum;
- one in-flight native command per episode;
- one in-flight model turn per room session;
- model action batch: at most `12` actions;
- run memory: at most `4096` UTF-8 bytes;
- bounded structural divergence diff: at most `256` entries;
- formal execution: serial native processes in v1.

Exact timeouts belong to versioned runtime configuration and must appear in the
episode fingerprint. An implementation must distinguish model idle timeout from
absolute model turn timeout.

Model-call efficiency SHOULD be reported as:

- calls per combat turn;
- calls per floor;
- input and cache-read tokens per floor;
- invalid/repair calls per run;
- wall time per native decision and model decision.

## 36. Testing strategy

### 36.1 Unit tests

Required coverage includes:

- strict JSON and duplicate-key rejection;
- canonicalization vectors;
- raw-state normalization;
- fairness allowlist and hidden-field leak tests;
- stable ID generation;
- every action schema and invalid-field case;
- legal-action generation for every normalized screen kind;
- stale identity/hash rejection;
- card and monster index re-resolution;
- sequential batch partial success;
- unsupported-screen hard stop;
- transition and chain hashing;
- replay structural validation;
- artifact redaction;
- process ownership matching;
- save fingerprint comparison;
- model response parsing and bounded repair;
- usage normalization with unavailable rather than zero values.

### 36.2 Fixture tests

Fixtures MUST cover at least:

- main menu;
- Neow;
- normal combat with one and multiple monsters;
- target and no-target cards;
- X-cost, unplayable, generated, retained, exhausted, and temporary-cost cards;
- potions with and without targets;
- full potion inventory reward;
- card reward and skip;
- combat reward with multiple reward types;
- map branching;
- event choices;
- shop purchases and removal;
- rest-site choices;
- treasure and boss reward;
- grid selection with exact and any-number cardinality;
- hand selection;
- death, Act 3 victory, and process exit;
- at least one upstream CommunicationMod known limitation;
- an unknown actionable screen.

Fixture provenance and fairness profile must be recorded. Fixtures containing
raw hidden state must never be copied into a model prompt test accidentally.

### 36.3 Native integration tests

The first native tests MUST use only the approved vanilla mod stack and fixed
seeds. They should progress from one command to one combat, one floor, one act,
and finally one complete run.

Integration evidence includes bridge logs, normalized states, action results,
save guards, process ownership, and artifact hashes. A launcher exit code alone
is not evidence of gameplay success.

### 36.4 Model tests

Automated unit tests MUST not contact a paid provider. Provider smoke tests are
explicit, bounded integration tests and require a real catalog check, real
minimal inference, exact model identity, and usage/error evidence.

## 37. Milestones

### M-1: Communication bridge compatibility probe

Deliverables:

- pinned bridge source provenance;
- reproducible Java 8-compatible build;
- verified ModTheSpire/BaseMod loading;
- `ready` handshake;
- main-menu state capture;
- fixed-seed Ironclad A0 start;
- one verified card play;
- one verified end turn;
- one verified non-combat choice;
- pre/post proof that normal saves and configuration did not change;
- captured fixtures for the exercised states.

M-1 explicitly excludes model integration and UI work.

### H1-A: Protocol and one-combat environment

Deliverables:

- sidecar public protocol;
- normalization and player-visible projection;
- stable identity model;
- legal actions and independent validation;
- `env.reset`, `env.observe`, `env.step`, and `env.close`;
- one complete fixed-seed combat without OS input;
- transition audit and offline replay verification;
- unit and fixture suite.

### H1-B: Complete vanilla run environment

Deliverables:

- every initial screen kind and action path;
- isolated one-process-per-episode launcher;
- complete Ironclad A0 run to native terminal state;
- metrics and artifact summary;
- repeated-seed live replay comparison;
- unsupported-screen and crash behavior;
- exact normal-data and install guards.

### H1-C: Scripted and tactical baselines

Deliverables:

- random-legal baseline;
- simple deterministic greedy baseline;
- optional tactical solver adapter;
- baseline result separation and metrics;
- no privileged observation unless explicitly labeled.

The scripted subset is independently acceptable once the random-legal and
deterministic greedy deliverables pass Section 38.3. The tactical solver adapter
is optional and remains a separately labeled later H1-C extension.

### H2: Model adapters and command center

Deliverables:

- ported AGY and OpenCode2 adapters;
- live model catalog and thinking variants;
- per-room sessions and bounded run memory;
- compact baseline/delta prompts;
- structured response and bounded repair;
- operator command center and audit view;
- `llm` and `hybrid_llm_solver` result separation;
- manual visual and live-provider acceptance left to the operator.

## 38. Acceptance gates

### 38.1 M-1 acceptance

M-1 passes only when:

1. the bridge JAR builds reproducibly from pinned inputs;
2. exact target hashes and enabled mods are recorded;
3. handshake and state parsing succeed;
4. card play, end turn, and one non-combat choice are verified from post-state;
5. no raw keyboard or coordinate action is used;
6. normal saves, preferences, Steam configuration, and unrelated mods remain
   unchanged;
7. only owned processes are stopped;
8. all exercised raw states are retained as redacted fixtures.

### 38.2 H1 acceptance

H1 passes only when:

1. all Python tests, Java tests, build checks, and script parse checks pass;
2. player-visible leak tests pass;
3. every initial decision kind has fixture coverage;
4. one isolated fixed-seed Ironclad A0 run reaches Act 3 victory or an authentic
   native defeat without manual input or unsupported fallback;
5. at least one run exercises combat, card reward, map, event, shop, rest,
   treasure, and boss reward paths across the acceptance corpus;
6. every reported action success has post-state evidence;
7. a repeated-seed scripted trace either achieves full required checkpoint
   parity or produces an accepted, explained narrower parity contract; silence
   or skipped comparison is not acceptance;
8. offline replay recomputes every transition and chain hash;
9. normal data and installation guards pass before and after every formal run;
10. no owned game or sidecar process remains after close;
11. no unrelated process is terminated;
12. failures and unsupported states remain explicit in the final report.

### 38.3 H1-C scripted-baseline acceptance

The H1-C scripted subset passes only when:

1. all project tests, builds, and script parse checks pass;
2. the suite configuration, policy descriptors, algorithms, policy seeds,
   limits, and configuration hash are retained;
3. `scripted_random_legal` and `scripted_greedy` each run every case in the same
   fixed native-seed matrix through separate isolated processes;
4. every policy input is `player_visible.v1` observation and legal-action data,
   with no raw, hidden, native-command, save, or cross-policy input;
5. every attempted action belongs to the current legal snapshot and every
   reported success has semantic post-state verification;
6. random draws and greedy rankings are independently reproducible from their
   recorded public inputs and versioned policy contracts;
7. the initial acceptance case for each policy reaches an authentic native
   victory or defeat; later benchmark suites may retain explicit truncations but
   may not call them terminal results;
8. offline replay, exact normal-data guards, descriptor ACLs, owned-process
   cleanup, and residual-process checks pass for every episode;
9. policy outcomes and episode metrics remain separated by policy ID; no H1-B
   acceptance run, blended score, omitted failure, or stale metric is counted;
10. model/provider usage fields are unavailable rather than zero;
11. an independent verifier rebuilds every H1 transition/action proof and every
    scripted policy-decision chain and reports no failure;
12. the report states that the optional tactical solver is not implemented and
    makes no tactical-solver performance claim.

### 38.4 H2 acceptance

H2 passes only when:

1. the selected provider/model exists in the live backend catalog;
2. one real minimal provider call succeeds with the exact selected model;
3. model output cannot bypass H1 validation;
4. stale responses from an earlier room or run are rejected;
5. unchanged stable states do not create duplicate model calls;
6. one combat uses one normal model call per player turn unless a documented
   mid-turn decision invalidates the remaining batch;
7. prompt artifacts contain no hidden raw state, credentials, save paths, or
   controller nonce;
8. usage and latency fields distinguish unavailable from zero;
9. pure LLM and hybrid results remain separate;
10. passive UI refresh is read-only;
11. automated checks complete before operator manual acceptance;
12. no automated UI tool claims manual acceptance on the operator's behalf.

## 39. Evidence-resolved decisions and remaining questions

### 39.1 Decisions resolved through H1-B

1. The Harness maintains a direct, pinned CommunicationMod fork under
   `vendor/CommunicationMod`. It is based on upstream commit
   `5e417eb189530986b9047a3c9426889fb261d146`.
2. The H1-B bridge is `1.2.1-sts-harness.2`, protocol
   `communicationmod-harness.v2`. The accepted reproducible JAR SHA-256 is
   `2C624F16E564902A572D421E2526E31271165B2B5B793861844DAAC76683B4DD`.
3. The accepted non-interactive launch invokes the pinned ModTheSpire JAR with
   `--skip-launcher`, `--skip-intro`, and exactly
   `basemod,CommunicationMod`. Harness episodes skip Steam API initialization;
   the formal launcher refuses to start while interactive `steam.exe` is
   active.
4. Each episode uses a unique profile/work root and redirects its working
   directory, `user.home`, `APPDATA`, `LOCALAPPDATA`, and `USERPROFILE`. Only a
   verified game-JAR hard link and the exact accepted mods are materialized.
   External pre/post guards cover the normal game tree, Workshop mods,
   ModTheSpire configuration, Steam manifest, and applicable Steam
   `localconfig.vdf`.
5. Native UUIDs, native counters, and Harness episode/session/run/room/combat/
   decision identities vary across same-seed executions. They remain in exact
   run-local integrity documents and are removed or semantically rebased only
   by `sts-replay-checkpoint.v1`.
6. Hand and card-in-play order and actionable current values are meaningful and
   strict. Draw, discard, exhaust, and limbo collections are semantic multisets
   for cross-run replay; the exact observation retains their player-visible
   contents and documented hidden-order boundary.
7. `sts-observation.v1` and `sts-legal-actions.v1` cover the initial vanilla
   main menu, Neow, combat, card/combat reward, map, event, shop, rest,
   treasure, boss reward, room completion, grid/hand selection, and terminal
   screens. Unknown actionable screens become an explicit unsupported hard
   stop rather than a generic native-command fallback.
8. The pinned bridge fork supplies the structured reward/inventory fields and
   action-settle behavior needed for verification. When potion inventory is
   full, the Harness suppresses a potion-take action that the upstream bridge
   could otherwise report as a silent success.
9. Cross-run live parity uses the exact, versioned projection in Section 25.2.
   It does not compare `observation_hash`, `legal_actions_hash`,
   `transition_hash`, or `chain_hash` across runs.
10. Player-visible card, relic, and potion names/descriptions and actionable
    current card values are included in the H1-B projection. Raw native
    identities and hidden state remain excluded from policy observations.

The accepted evidence for these decisions is indexed in
`docs/H1B_ACCEPTANCE.md`.

### 39.2 Questions remaining after H1-B

1. Whether native framebuffer capture can be added without OS-level desktop
   capture.
2. Whether a later benchmark should automatically enter Act 4 after an Act 3
   victory with all three keys.
3. Whether a future tactical solver will model only player-visible uncertainty
   or receive separately labeled oracle state.
4. What additional resource and profile isolation must be proven before
   parallel native runs can be authorized.

These questions belong to later baseline, model, visual, or parallel-execution
work and do not widen H1-B. They are not permission to choose a broader or less
safe fallback. If one blocks a later milestone, the implementation must stop
and record the exact evidence needed to resolve it.

## 40. Versioning and change control

The following are independently versioned:

- this specification;
- bridge protocol;
- public JSON-RPC API;
- normalized exported state;
- player-visible observation;
- legal-action document;
- action batch;
- transition document;
- reward vector;
- run memory;
- model response;
- canonical hash encoding;
- benchmark configuration and score policy.

A breaking field or semantic change increments the applicable major version.
Adding an optional observation field may increment a minor version only when
the fairness review confirms it does not leak hidden information. Historical
artifacts retain their original versions and are never silently rewritten.

The implementation must update this document or a linked normative document
before widening the supported character, ascension, content-mod, fairness, or
mutation scope.

## 41. Initial implementation order

The required order is:

1. pin and build the Java bridge;
2. prove protocol handshake and stdout purity;
3. capture raw fixtures;
4. prove normal-data isolation;
5. implement normalization and fairness projection;
6. implement stable IDs and legal actions;
7. implement one-action execution and post-state verification;
8. implement sequential batches;
9. implement the H1 episode API and artifacts;
10. cover all initial screens;
11. complete repeated-seed replay work;
12. complete a full scripted native run;
13. add baselines;
14. port model backends;
15. add the command center and screenshots.

Model prompting, provider integration, and visual polish MUST NOT be used to
paper over an incomplete H1 state/action contract.

## 42. References

- [ModTheSpire](https://github.com/kiooeht/ModTheSpire)
- [BaseMod](https://github.com/daviscook477/BaseMod)
- [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)
- [spirecomm](https://github.com/ForgottenArbiter/spirecomm)
- [Kingdom Rush Harness specification](../kingdom-rush-harness/SPEC.md)
- [Kingdom Rush H1 episode contract](../kingdom-rush-harness/docs/H1_EPISODE_API.md)
- [Kingdom Rush OpenCode2 adapter contract](../kingdom-rush-harness/docs/H2_OPENCODE2.md)

References are informative unless a requirement in this specification makes a
specific pinned version or behavior normative. External repositories must be
recorded by exact revision before their code or protocol is used in an accepted
build.
