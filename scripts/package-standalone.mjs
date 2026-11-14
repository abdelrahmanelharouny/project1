import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { resolve, relative, join, isAbsolute } from 'node:path';

const root = process.cwd();
const dist = resolve(root, process.env.NEXT_DIST_DIR || '.next');
const distName = relative(root, dist);
if (!distName || distName.startsWith('..') || isAbsolute(distName)) {
  throw new Error('NEXT_DIST_DIR must be a build directory inside the repository');
}
const standalone = join(dist, 'standalone');
if (!existsSync(standalone)) throw new Error('Next standalone output is missing');
mkdirSync(join(standalone, distName), { recursive: true });
cpSync(join(dist, 'static'), join(standalone, distName, 'static'), { recursive: true });
cpSync(join(root, 'public'), join(standalone, 'public'), { recursive: true });
