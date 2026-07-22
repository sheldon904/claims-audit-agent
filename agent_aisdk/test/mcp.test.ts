import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { createMCPClient } from '@ai-sdk/mcp';
import { generateText, stepCountIs } from 'ai';
import { MockLanguageModelV4 } from 'ai/test';
import { z } from 'zod';
import { afterEach, describe, expect, it } from 'vitest';

/**
 * Proves the AI SDK MCP client can source a tool from an MCP server and hand it
 * to the model — the same code path used against the real `sparql-mcp`, but
 * driven by an in-process server so it runs offline in CI with no ports.
 */
describe('AI SDK MCP client wiring', () => {
  let close: (() => Promise<void>) | undefined;

  afterEach(async () => {
    if (close) await close();
    close = undefined;
  });

  async function connectEcho() {
    const server = new McpServer({ name: 'echo-server', version: '0.0.0' });
    server.registerTool(
      'echo',
      { description: 'Echo back the given text.', inputSchema: { text: z.string() } },
      ({ text }: { text: string }) => ({ content: [{ type: 'text' as const, text }] }),
    );
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = await createMCPClient({ transport: clientTransport });
    close = () => client.close();
    return client;
  }

  it('discovers a tool over MCP and exposes it as an AI SDK tool', async () => {
    const client = await connectEcho();
    const tools = await client.tools();
    expect(Object.keys(tools)).toContain('echo');
  });

  it('a model can actually call the MCP-sourced tool through generateText', async () => {
    const client = await connectEcho();
    const tools = await client.tools();

    // Mock model: call `echo` once, then stop. This exercises the full path —
    // MCP tool discovery -> tool execution over the transport -> tool result.
    let step = 0;
    const model = new MockLanguageModelV4({
      doGenerate: () => {
        const first = step === 0;
        step += 1;
        return Promise.resolve(
          first
            ? {
                content: [
                  {
                    type: 'tool-call' as const,
                    toolCallId: 'c1',
                    toolName: 'echo',
                    input: JSON.stringify({ text: 'ping' }),
                  },
                ],
                finishReason: { unified: 'tool-calls' as const, raw: undefined },
                usage: {
                  inputTokens: {
                    total: 1,
                    noCache: 1,
                    cacheRead: undefined,
                    cacheWrite: undefined,
                  },
                  outputTokens: { total: 1, text: 1, reasoning: undefined },
                },
                warnings: [],
              }
            : {
                content: [{ type: 'text' as const, text: 'done' }],
                finishReason: { unified: 'stop' as const, raw: undefined },
                usage: {
                  inputTokens: {
                    total: 1,
                    noCache: 1,
                    cacheRead: undefined,
                    cacheWrite: undefined,
                  },
                  outputTokens: { total: 1, text: 1, reasoning: undefined },
                },
                warnings: [],
              },
        );
      },
    });

    const result = await generateText({
      model,
      tools,
      stopWhen: stepCountIs(4),
      prompt: 'echo ping',
    });

    const echoResult = result.steps
      .flatMap((s) => s.toolResults)
      .find((tr) => tr.toolName === 'echo');
    expect(echoResult).toBeDefined();
  });
});
