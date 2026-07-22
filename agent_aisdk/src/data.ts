/**
 * Dataset loading — reads the *frozen, committed* holdout and full sets from
 * `data/` (never writes them). Mirrors `evals/harness.py` `load_holdout` /
 * `load_full`, so the TypeScript arm audits byte-identical claims to the Python
 * arms and is scored on the same ground truth.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { type Claim, ClaimSchema, type Finding, FindingSchema } from './models.js';
import { DATA_DIR } from './paths.js';

export type Dataset = 'holdout' | 'full';

export interface LoadedData {
  claims: Claim[];
  groundTruth: Map<string, Finding[]>;
}

function parseFindings(items: unknown): Finding[] {
  return z_arrayFindings(items);
}

// Small local helper kept explicit for clarity (avoids importing zod here just
// for one array parse).
function z_arrayFindings(items: unknown): Finding[] {
  if (!Array.isArray(items)) return [];
  return items.map((it) => FindingSchema.parse(it));
}

export function loadHoldout(dataDir: string = DATA_DIR): LoadedData {
  const raw = JSON.parse(readFileSync(resolve(dataDir, 'holdout.json'), 'utf-8')) as {
    claims: unknown[];
    ground_truth: Record<string, unknown>;
  };
  const claims = raw.claims.map((c) => ClaimSchema.parse(c));
  const groundTruth = new Map<string, Finding[]>();
  for (const [cid, fs] of Object.entries(raw.ground_truth)) {
    groundTruth.set(cid, parseFindings(fs));
  }
  return { claims, groundTruth };
}

export function loadFull(dataDir: string = DATA_DIR): LoadedData {
  const claimsRaw = JSON.parse(readFileSync(resolve(dataDir, 'claims.json'), 'utf-8')) as unknown[];
  const gtRaw = JSON.parse(
    readFileSync(resolve(dataDir, 'ground_truth.json'), 'utf-8'),
  ) as Record<string, unknown>;
  const claims = claimsRaw.map((c) => ClaimSchema.parse(c));
  const groundTruth = new Map<string, Finding[]>();
  for (const [cid, fs] of Object.entries(gtRaw)) {
    groundTruth.set(cid, parseFindings(fs));
  }
  return { claims, groundTruth };
}

export function loadDataset(name: Dataset): LoadedData {
  return name === 'full' ? loadFull() : loadHoldout();
}
