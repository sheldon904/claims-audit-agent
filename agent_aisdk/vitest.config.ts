import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    // The MCP wiring test spins up an in-process stdio server; give it room.
    testTimeout: 20000,
  },
});
