package communicationmod.patches;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePrefixPatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireReturn;
import com.codedisaster.steamworks.SteamAPI;
import com.codedisaster.steamworks.SteamException;
import com.megacrit.cardcrawl.integrations.steam.SteamIntegration;

/**
 * Prevents an isolated harness episode from touching the operator's live Steam
 * session. Normal CommunicationMod launches continue through the stock
 * SteamIntegration constructor unchanged.
 */
@SpirePatch(
        clz = SteamIntegration.class,
        method = SpirePatch.CONSTRUCTOR
)
public class HarnessDisableSteamIntegrationPatch {
    @SpirePrefixPatch
    public static SpireReturn<Void> disableForIsolatedHarness() {
        String episodeId = System.getenv("STS_HARNESS_EPISODE_ID");
        if (episodeId != null && !episodeId.trim().isEmpty()) {
            try {
                // CardCrawlGame later constructs SteamUtils unconditionally, so
                // the JNI library must exist even though no client handshake is
                // allowed for an isolated harness episode.
                SteamAPI.loadLibraries();
            } catch (SteamException error) {
                throw new RuntimeException("Harness could not load steamworks JNI", error);
            }
            return SpireReturn.Return(null);
        }
        return SpireReturn.Continue();
    }
}
