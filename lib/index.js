import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

export const name = 'youtube-study-notes-dsh';
export const PACKAGE_NAME = 'dsh-youtube-study-notes';

/**
 * Resolve the packaged Skill root from the DSH profile's own module resolution.
 *
 * The bundle ships no runtime plugin logic — its substance is the Skill under
 * `skills/`. This helper exists so the root is derived from the package's npm
 * identity as resolved by the installing profile, which stays correct for
 * hoisted, nested and linked installs alike.
 *
 * @param profileBaseUrl - Loader `baseUrl` of the profile that installed this bundle.
 * @returns absolute path of the `skills` directory shipped by this package.
 */
export function resolveSkillRoot(profileBaseUrl) {
  if (!profileBaseUrl) {
    throw new Error('dsh-youtube-study-notes: missing DSH profile baseUrl for package resolution');
  }
  let manifestPath;
  try {
    manifestPath = createRequire(profileBaseUrl).resolve(`${PACKAGE_NAME}/package.json`);
  } catch (error) {
    throw new Error(
      `dsh-youtube-study-notes: cannot resolve ${PACKAGE_NAME}/package.json from the DSH profile`,
      { cause: error },
    );
  }
  return join(dirname(manifestPath), 'skills');
}
