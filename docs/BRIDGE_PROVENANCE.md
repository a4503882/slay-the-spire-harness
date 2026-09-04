# Bridge provenance

The M-1 bridge is a local fork of
[ForgottenArbiter/CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod).

- upstream commit: `5e417eb189530986b9047a3c9426889fb261d146`
- upstream commit date: `2023-01-19T21:40:58-07:00`
- upstream version: `1.2.1`
- upstream license: MIT; retained in `vendor/CommunicationMod/LICENSE`
- local bridge version: `1.2.1-sts-harness.1`

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
- Maven Shade Plugin is pinned to `3.6.2` for the current JDK toolchain;
- the upstream post-package copy into a fixed mods directory is removed.

No game binary, ModTheSpire JAR, BaseMod JAR, or game asset is copied into the
source tree.
