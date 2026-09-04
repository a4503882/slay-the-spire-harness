# Vendored CommunicationMod provenance

- upstream: `https://github.com/ForgottenArbiter/CommunicationMod.git`
- upstream commit: `5e417eb189530986b9047a3c9426889fb261d146`
- upstream branch at import: `master`
- Harness bridge version: `1.2.1-sts-harness.1`

The top-level repository tracks this directory as vendored source, not as a Git
submodule. The H1-A bridge patch modifies exactly these six upstream files:

- `pom.xml`
- `src/main/java/communicationmod/CommunicationMod.java`
- `src/main/java/communicationmod/DataReader.java`
- `src/main/java/communicationmod/DataWriter.java`
- `src/main/java/communicationmod/GameStateConverter.java`
- `src/main/resources/ModTheSpire.json`

The original nested `.git` metadata was moved, without deletion, to the ignored
local path `.tools/vendor-git/CommunicationMod.git` when the top-level private
repository was initialized. It can be used with explicit `--git-dir` and
`--work-tree` arguments for upstream archaeology without turning the vendored
directory back into an accidental gitlink.
