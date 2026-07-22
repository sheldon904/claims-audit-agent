/**
 * MCP probe — connects to the repo's `sparql-mcp` server through the Vercel AI
 * SDK's MCP client, discovers its tools, and writes the discovered schemas to a
 * committed artifact (`artifacts/mcp-sparql-tools.json`). This is the evidence
 * behind the README's MCP paragraph: it proves the AI SDK arm can source a tool
 * from an external MCP server over one standard interface.
 *
 * Tool discovery is served by the MCP server itself and does not require the
 * upstream SPARQL store, so this is reproducible against a freshly-started
 * `sparql-mcp` with no triple store attached.
 *
 * Usage:
 *   MCP_SPARQL_URL=http://127.0.0.1:4002/sse npm run mcp:probe
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { connectSparqlMcp, describeTools } from '../src/mcp.js';

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, '..', 'artifacts', 'mcp-sparql-tools.json');

async function main(): Promise<void> {
  const url = process.env['MCP_SPARQL_URL'] ?? 'http://127.0.0.1:4002/sse';
  process.stderr.write(`[mcp-probe] connecting to ${url} ...\n`);
  const conn = await connectSparqlMcp(url);
  const discovered = describeTools(conn.tools);
  await conn.close();

  const artifact = {
    server: 'sparql-mcp',
    transport: 'sse',
    url,
    discovered_tools: discovered.map((t) => t.name),
    tool_count: discovered.length,
    tools: discovered,
  };
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(artifact, null, 2)}\n`, 'utf-8');
  process.stderr.write(
    `[mcp-probe] discovered ${discovered.length} tool(s): ${discovered
      .map((t) => t.name)
      .join(', ')}\n[mcp-probe] wrote ${OUT}\n`,
  );
}

main().catch((err: unknown) => {
  process.stderr.write(`[mcp-probe] failed: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exitCode = 1;
});
