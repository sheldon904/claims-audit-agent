/**
 * Locate the repository root so the TypeScript arm can read the *canonical,
 * frozen* `data/` and `rules/` files rather than duplicating them. Walking up
 * from the module directory works whether this file runs from `src/` (via tsx)
 * or `dist/` (via node), and whether invoked from the arm dir or the repo root.
 */
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function findRepoRoot(startDir?: string): string {
  let dir = startDir ?? dirname(fileURLToPath(import.meta.url));
  // Ascend until we find the canonical rule set + dataset directory.
  for (let i = 0; i < 8; i += 1) {
    if (
      existsSync(resolve(dir, 'rules', 'audit_rules.yaml')) &&
      existsSync(resolve(dir, 'data', 'holdout.json'))
    ) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    'Could not locate repo root (rules/audit_rules.yaml + data/holdout.json) ' +
      'walking up from ' +
      (startDir ?? dirname(fileURLToPath(import.meta.url))),
  );
}

export const REPO_ROOT = findRepoRoot();
export const RULES_PATH = resolve(REPO_ROOT, 'rules', 'audit_rules.yaml');
export const DATA_DIR = resolve(REPO_ROOT, 'data');
