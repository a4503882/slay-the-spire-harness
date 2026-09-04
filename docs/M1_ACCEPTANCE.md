# M-1 acceptance report

## Result

M-1 passed its first isolated native probe on 2026-09-04.

- run ID: `m1-20260904-170257-0075eb79`
- seed: `AMIYA20260904`
- run report:
  `artifacts/m1-runs/m1-20260904-170257-0075eb79/m1-report.json`
- worker status: `passed`
- timeout: `false`
- owned process tree stopped: `true`
- normal-data guard unchanged: `true`
- normal-data changes: `0`
- independent evidence verification: `valid=true`, `16/16` checks passed

This is automated protocol and native-state evidence. It is not an operator
visual acceptance of the game UI and does not claim H1-A completion.

The independent verification artifact is
`artifacts/m1-runs/m1-20260904-170257-0075eb79/m1-independent-verification.json`
with SHA-256
`4A788CEC6D0AFE1BBF53FB80836C8C6D93B3FF915A414D98317765B85D33EB3F`.

## Target and bridge

- Steam app: `646570`
- Steam build: `10180494`
- game JAR SHA-256:
  `CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673`
- ModTheSpire: `3.30.3`
- BaseMod: `5.56.0`
- bridge upstream commit:
  `5e417eb189530986b9047a3c9426889fb261d146`
- bridge version: `1.2.1-sts-harness.1`
- bridge JAR bytes: `356040`
- bridge JAR SHA-256:
  `683A47733B8AF84E7248189C2DC79AD4DD57EC5F03FBF08F1BA49F5F06C98D2C`
- Java bytecode major version: `52` (Java 8)
- Maven: `3.9.16`, downloaded to the project tool cache after pinned SHA-512
  verification
- Maven Shade Plugin: `3.6.2`

Two consecutive clean builds produced the same JAR byte count and SHA-256.

## Loaded mod evidence

The ModTheSpire log reported:

- `ModTheSpire (3.30.3)`;
- `CommunicationMod (1.2.1-sts-harness.1)`;
- BaseMod initialization;
- `Communication Mod (StS Harness)` initialization;
- strict `Received ready signal from external process`;
- `Starting game`.

No gameplay content mod was selected by the launch command. The isolated
working directory contained only `BaseMod.jar` and `CommunicationMod.jar` under
its local `mods` directory.

## Native transition evidence

The worker received eight stable states and sent seven commands:

1. `start ironclad 0 AMIYA20260904`
2. `choose 0`
3. `choose 0`
4. `choose 0`
5. `choose 0`
6. `play 1 0`
7. `end`

Observed state sequence:

1. main menu, `start` available;
2. Neow event, `choose` available;
3. Neow event continuation;
4. Neow event continuation;
5. map choice;
6. floor-1 `MonsterRoom`, combat turn 1;
7. combat turn 1 after the selected card left the hand;
8. combat turn 2 after the end-turn command.

The worker independently marked all required evidence true:

- `start_verified=true`;
- `non_combat_choice_verified=true`;
- `card_play_verified=true`;
- `end_turn_verified=true`.

Every verification records a distinct before/after raw exported-state SHA-256.
The card-play verifier required the selected raw UUID to leave the stable hand
or combat to end. The end-turn verifier required the native turn number to
increase or combat to end.

## Isolation and guard evidence

The game ran from a unique working directory under the M-1 artifact root. Its
`desktop-1.0.jar` was a hard link to one verified ignored tool-cache copy, so
subsequent episodes do not create another 365 MB physical copy.

The child environment redirected:

- `LOCALAPPDATA`;
- `APPDATA`;
- `USERPROFILE`;
- Java `user.home`;
- game working directory;
- ModTheSpire config;
- game `preferences`, `saves`, logs, and bridge stderr.

The normal-data guard covered:

- the normal game installation and save directories;
- the Slay the Spire Workshop content directory;
- normal ModTheSpire local configuration;
- Steam app manifest `646570`;
- discovered Steam `localconfig.vdf` files.

Pre-run and post-run aggregate guard digest:

`sha256:c670ac0cc7794b2ba528eba4e002a26c2186e1bde367b40adc4c56fba131c473`

The before and after guard documents were byte-identical and the structured
comparison reported zero changed roots.

The isolated profile received its own ModTheSpire configuration, BaseMod files,
GPU cache, game display files, run autosave, and game log. None were written to
the normal roots.

## Expected warnings

- `Could not connect to Steam. Is it running?` was emitted because the game was
  launched directly from the isolated Java/ModTheSpire path. The native probe
  still completed and Steam Cloud was not used.
- BaseMod logged a missing `console-history.txt` in the new isolated profile.
  It continued by creating its normal isolated config and does not affect the
  bridge or gameplay evidence.
- JDK 21 emitted localized warnings for Java 8 `source`/`target`. The output
  class was independently verified as major version 52.

## Acceptance boundary

M-1 proves only the compatibility slice required by `SPEC.md`:

- reproducible bridge build;
- strict ready handshake;
- isolated native launch;
- structured raw state receipt;
- one native card play;
- one native end turn;
- non-combat choices;
- post-state verification;
- normal-data preservation;
- exact owned-process cleanup.

It does not yet provide the public JSON-RPC sidecar, player-visible projection,
stable agent IDs, complete legal-action schema, full combat, replay chain, or
model integration. Those begin in H1-A.
