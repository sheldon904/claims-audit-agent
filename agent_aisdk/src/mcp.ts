/**
 * MCP wiring — one tool sourced through the Vercel AI SDK's MCP client from a
 * real, separately-running MCP server (the repo's `sparql-mcp`, an Express + SSE
 * server that exposes a read-only SPARQL endpoint as agent tools).
 *
 * This is an ADDITIONAL capability, deliberately kept OUT of the scored audit
 * loop: the benchmark must stay reproducible without any external server, so the
 * four audit tools remain in-process. When `--mcp <url>` is passed, the AI SDK
 * connects over SSE, discovers `sparql-mcp`'s tools, and exposes them alongside
 * the audit tools — demonstrating that a tool from an external MCP server can be
 * dropped into this arm through one standard interface.
 *
 * Tool discovery (`client.tools()`) is served by the MCP server itself and does
 * NOT require the upstream SPARQL store to be up, which is what makes the demo
 * reproducible: `npm run mcp:probe` connects and captures the discovered tool
 * schemas as a committed artifact.
 */
import { createMCPClient } from '@ai-sdk/mcp';
import type { ToolSet } from 'ai';

export const DEFAULT_SPARQL_MCP_URL = 'http://127.0.0.1:4002/sse';

export interface McpConnection {
  tools: ToolSet;
  toolNames: string[];
  close: () => Promise<void>;
}

/**
 * Connect to `sparql-mcp` over SSE and return its tools as AI SDK tools, ready
 * to merge into a `generateText` call. Caller must `close()` when done.
 */
export async function connectSparqlMcp(
  url: string = DEFAULT_SPARQL_MCP_URL,
): Promise<McpConnection> {
  const client = await createMCPClient({ transport: { type: 'sse', url } });
  const tools = await client.tools();
  return {
    tools,
    toolNames: Object.keys(tools),
    close: () => client.close(),
  };
}

/** JSON-serialisable view of a discovered tool, for the committed artifact. */
export interface DiscoveredTool {
  name: string;
  description: string | undefined;
  inputSchema: unknown;
}

export function describeTools(tools: ToolSet): DiscoveredTool[] {
  return Object.entries(tools).map(([name, t]) => ({
    name,
    description: (t as { description?: string }).description,
    inputSchema: (t as { inputSchema?: unknown }).inputSchema,
  }));
}
