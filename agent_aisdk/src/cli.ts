#!/usr/bin/env node
/**
 * CLI entrypoint for the Vercel AI SDK audit arm.
 *
 * Takes claim ids (or a whole dataset) and emits findings as JSON in the exact
 * shape the canonical Python eval harness consumes, so the harness stays the
 * single source of truth for scoring and is never modified. All human-readable
 * progress goes to stderr; stdout is pure JSON.
 *
 * Examples
 *   node dist/cli.js CLM-00001 CLM-00002              # audit specific claims
 *   node dist/cli.js --dataset holdout --all          # audit the frozen holdout
 *   node dist/cli.js --dataset holdout --all --mock    # offline oracle (no key)
 *   node dist/cli.js --all --thinking on               # extended thinking
 *   node dist/cli.js CLM-00001 --mcp http://127.0.0.1:4002/sse   # + sparql-mcp tools
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { auditClaim, type ClaimAuditResult, DEFAULT_MAX_STEPS } from './agent.js';
import { AuditContext } from './context.js';
import { type Dataset, loadDataset } from './data.js';
import { connectSparqlMcp } from './mcp.js';
import { buildOracleModel } from './mock.js';
import { REPO_ROOT } from './paths.js';
import { buildConfig, buildModel } from './provider.js';
import { loadRules } from './rules.js';

interface CliArgs {
  claimIds: string[];
  dataset: Dataset;
  all: boolean;
  limit: number | undefined;
  thinking: boolean;
  provider: string;
  model: string | undefined;
  mock: boolean;
  mcpUrl: string | undefined;
  timeoutMs: number | undefined;
  maxSteps: number;
  out: string | undefined;
  pretty: boolean;
}

function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    claimIds: [],
    dataset: 'holdout',
    all: false,
    limit: undefined,
    thinking: false,
    provider: 'auto',
    model: undefined,
    mock: false,
    mcpUrl: undefined,
    timeoutMs: undefined,
    maxSteps: DEFAULT_MAX_STEPS,
    out: undefined,
    pretty: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = (): string => {
      const v = argv[i + 1];
      if (v === undefined) throw new Error(`missing value for ${a}`);
      i += 1;
      return v;
    };
    switch (a) {
      case '--dataset':
        args.dataset = next() === 'full' ? 'full' : 'holdout';
        break;
      case '--all':
        args.all = true;
        break;
      case '--limit':
        args.limit = Number.parseInt(next(), 10);
        break;
      case '--thinking':
        args.thinking = next() === 'on';
        break;
      case '--provider':
        args.provider = next();
        break;
      case '--model':
        args.model = next();
        break;
      case '--mock':
        args.mock = true;
        break;
      case '--mcp':
        args.mcpUrl = next();
        break;
      case '--timeout-ms':
        args.timeoutMs = Number.parseInt(next(), 10);
        break;
      case '--max-steps':
        args.maxSteps = Number.parseInt(next(), 10);
        break;
      case '--out':
        args.out = next();
        break;
      case '--pretty':
        args.pretty = true;
        break;
      default:
        if (a !== undefined && a.startsWith('--')) throw new Error(`unknown flag ${a}`);
        if (a !== undefined) args.claimIds.push(a);
    }
  }
  return args;
}

function loadEnv(): void {
  try {
    process.loadEnvFile(resolve(REPO_ROOT, '.env'));
  } catch {
    // no .env — env vars may still be set in the shell; that's fine.
  }
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  loadEnv();

  const ruleset = loadRules();
  const { claims, groundTruth } = loadDataset(args.dataset);
  const ctx = AuditContext.build(claims, ruleset);

  let claimIds = args.claimIds.length > 0 ? args.claimIds : args.all ? claims.map((c) => c.claim_id) : [];
  if (claimIds.length === 0) {
    process.stderr.write('No claims selected. Pass claim ids or --all.\n');
    return 2;
  }
  if (args.limit !== undefined) claimIds = claimIds.slice(0, args.limit);

  const cfg = buildConfig({ model: args.model, thinking: args.thinking, provider: args.provider });

  // Optional: wire an external MCP server's tools into the agent (demonstration;
  // not used for the scored benchmark). Tool discovery needs no SPARQL backend.
  let mcpClose: (() => Promise<void>) | undefined;
  let extraTools: import('ai').ToolSet | undefined;
  if (args.mcpUrl !== undefined && !args.mock) {
    const conn = await connectSparqlMcp(args.mcpUrl);
    extraTools = conn.tools;
    mcpClose = conn.close;
    process.stderr.write(`[mcp] connected ${args.mcpUrl} — tools: ${conn.toolNames.join(', ')}\n`);
  }

  const providerLabel = args.mock ? 'mock' : cfg.provider;
  const modelLabel = args.mock ? 'oracle' : cfg.model;
  process.stderr.write(
    `[aisdk] dataset=${args.dataset} claims=${claimIds.length} provider=${providerLabel} ` +
      `model=${modelLabel} thinking=${args.thinking ? 'on' : 'off'}\n`,
  );

  // One warm model for real runs; per-claim oracle models for --mock.
  const sharedModel = args.mock ? null : buildModel(cfg);
  const results: ClaimAuditResult[] = [];
  for (const claimId of claimIds) {
    const model = sharedModel ?? buildOracleModel(groundTruth.get(claimId) ?? []);
    const r = await auditClaim(ctx, claimId, model, {
      cfg,
      maxSteps: args.maxSteps,
      timeoutMs: args.timeoutMs,
      extraTools,
    });
    const suffix = r.error ? ` error=${r.error}` : '';
    process.stderr.write(
      `[aisdk] ${claimId}: ${r.findings.length} finding(s) ` +
        `${r.latency_ms.toFixed(0)}ms steps=${r.steps}${suffix}\n`,
    );
    results.push(r);
  }

  if (mcpClose) await mcpClose();

  const envelope = {
    arm: 'vercel-ai-sdk',
    provider: providerLabel,
    model: modelLabel,
    thinking: args.thinking ? 'on' : 'off',
    dataset: args.dataset,
    mcp: args.mcpUrl ?? null,
    results,
  };
  const json = args.pretty ? JSON.stringify(envelope, null, 2) : JSON.stringify(envelope);
  if (args.out !== undefined) {
    writeFileSync(args.out, `${json}\n`, 'utf-8');
    process.stderr.write(`[aisdk] wrote ${args.out}\n`);
  }
  process.stdout.write(`${json}\n`);
  return 0;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((err: unknown) => {
    process.stderr.write(`[aisdk] fatal: ${err instanceof Error ? err.stack : String(err)}\n`);
    process.exitCode = 1;
  });
