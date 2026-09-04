# Bridge provenance

The M-1 bridge is a local fork of
[ForgottenArbiter/CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod).

- upstream commit: `5e417eb189530986b9047a3c9426889fb261d146`
- upstream commit date: `2023-01-19T21:40:58-07:00`
- upstream version: `1.2.1`
- upstream license: MIT; retained in `vendor/CommunicationMod/LICENSE`
- H1-A bridge version: `1.2.1-sts-harness.1`
- current H1-B bridge version: `1.2.1-sts-harness.2`

The local M-1 patch is intentionally narrow:

- local dependency paths come from `STS_GAME_JAR`, `STS_MTS_JAR`, and
  `STS_BASEMOD_JAR` rather than checked-in proprietary JARs;
- the bridge worker command comes from `STS_HARNESS_PYTHON` and
  `STS_HARNESS_WORKER`, preserving paths with spaces and keeping the command out
  of persistent config;
- `STS_HARNESS_AUTOSTART=1` enables child-only automatic startup;
- the initialization signal must be exactly `ready`, ignoring case and outer
  whitespace;
- bridge input and output use explicit UTF-8;
- end-of-stream terminates the reader instead of spinning;
- raw state documents identify bridge and protocol versions;
- H1-B adds player-visible card base/current values and visible descriptions for
  cards, relics, and potions; this additive raw protocol revision is
  `communicationmod-harness.v2`;
- consumed combat rewards are tracked by native reward identity so a completed
  card reward cannot reappear after the stock game resets its `isDone` flag;
- delayed card-obtain effects and temporary living-monster `DEBUG` intents are
  not published as stable command boundaries;
- boss relic selection activates the existing equip barrier before the native
  click so ownership is observable before the next decision;
- isolated harness launches load the steamworks JNI required by the stock game
  but skip `SteamAPI.init`; normal CommunicationMod launches retain the upstream
  Steam behavior;
- Maven Shade Plugin is pinned to `3.6.2` for the current JDK toolchain;
- the upstream post-package copy into a fixed mods directory is removed.

No game binary, ModTheSpire JAR, BaseMod JAR, or game asset is copied into the
source tree.
