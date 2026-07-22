/**
 * LLM provider factory for the AI SDK arm — the TypeScript analogue of
 * `providers/chat.py`. It resolves provider + model + credentials from the same
 * environment variables (so the whole repo shares one backend convention) and
 * builds a Vercel AI SDK `LanguageModel` via `@ai-sdk/anthropic`.
 *
 * Provider precedence (mirrors `resolve_provider`):
 *   explicit arg | $LLM_PROVIDER | "openrouter" if $OPENROUTER_API_KEY | "anthropic"
 *
 * OpenRouter is reached through its Anthropic-compatible endpoint: the
 * `@ai-sdk/anthropic` provider POSTs to `{baseURL}/messages`, and OpenRouter
 * serves that at `https://openrouter.ai/api/v1/messages`. Auth is a bearer token
 * (`authToken`), which is exactly what OpenRouter expects — the same finding the
 * `claude-agent-sdk` arm relies on (`ANTHROPIC_AUTH_TOKEN`).
 */
import { createAnthropic } from '@ai-sdk/anthropic';
import type { LanguageModel } from 'ai';

export type Provider = 'anthropic' | 'openrouter';

export const DEFAULT_ANTHROPIC_MODEL = 'claude-sonnet-5';
export const DEFAULT_OPENROUTER_MODEL = 'anthropic/claude-sonnet-4.5';
export const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1';
export const DEFAULT_MAX_TOKENS = 8000;
export const DEFAULT_THINKING_TOKENS = 4000;

const OPENROUTER_MODEL_MAP: Record<string, string> = {
  'claude-sonnet-5': 'anthropic/claude-sonnet-4.5',
  'claude-opus-4-8': 'anthropic/claude-opus-4.1',
  'claude-haiku-4-5-20251001': 'anthropic/claude-haiku-4.5',
};

export interface ProviderConfig {
  provider: Provider;
  model: string;
  thinking: boolean;
  apiKey: string | undefined;
  baseURL: string | undefined;
  maxTokens: number;
  thinkingTokens: number;
  siteUrl?: string | undefined;
  appName?: string | undefined;
}

export function resolveProvider(explicit?: string): Provider {
  if (explicit && explicit !== 'auto') return explicit as Provider;
  const env = process.env['LLM_PROVIDER'];
  if (env) return env.trim().toLowerCase() as Provider;
  if (process.env['OPENROUTER_API_KEY']) return 'openrouter';
  return 'anthropic';
}

function resolveOpenRouterModel(canonical?: string): string {
  const override = process.env['OPENROUTER_MODEL'];
  if (override) return override;
  if (canonical && canonical in OPENROUTER_MODEL_MAP) {
    const mapped = OPENROUTER_MODEL_MAP[canonical];
    if (mapped) return mapped;
  }
  if (canonical && canonical.includes('/')) return canonical;
  return DEFAULT_OPENROUTER_MODEL;
}

export function buildConfig(opts: {
  model?: string | undefined;
  thinking?: boolean;
  provider?: string | undefined;
}): ProviderConfig {
  const provider = resolveProvider(opts.provider);
  const thinking = opts.thinking ?? false;
  if (provider === 'openrouter') {
    return {
      provider,
      model: resolveOpenRouterModel(opts.model),
      thinking,
      apiKey: process.env['OPENROUTER_API_KEY'],
      baseURL: process.env['OPENROUTER_BASE_URL'] ?? OPENROUTER_BASE_URL,
      maxTokens: DEFAULT_MAX_TOKENS,
      thinkingTokens: DEFAULT_THINKING_TOKENS,
      siteUrl: process.env['OPENROUTER_SITE_URL'],
      appName: process.env['OPENROUTER_APP_NAME'] ?? 'claims-audit-agent',
    };
  }
  return {
    provider,
    model: opts.model ?? process.env['ANTHROPIC_MODEL'] ?? DEFAULT_ANTHROPIC_MODEL,
    thinking,
    apiKey: process.env['ANTHROPIC_API_KEY'],
    baseURL: process.env['ANTHROPIC_BASE_URL'],
    maxTokens: DEFAULT_MAX_TOKENS,
    thinkingTokens: DEFAULT_THINKING_TOKENS,
  };
}

/** Instantiate the AI SDK language model for `cfg`. */
export function buildModel(cfg: ProviderConfig): LanguageModel {
  if (cfg.provider === 'openrouter') {
    const headers: Record<string, string> = {};
    if (cfg.siteUrl) headers['HTTP-Referer'] = cfg.siteUrl;
    if (cfg.appName) headers['X-Title'] = cfg.appName;
    const anthropic = createAnthropic({
      baseURL: cfg.baseURL ?? OPENROUTER_BASE_URL,
      authToken: cfg.apiKey ?? 'MISSING',
      headers,
    });
    return anthropic(cfg.model);
  }
  const anthropic = createAnthropic({
    ...(cfg.apiKey ? { apiKey: cfg.apiKey } : {}),
    ...(cfg.baseURL ? { baseURL: cfg.baseURL } : {}),
  });
  return anthropic(cfg.model);
}

/**
 * Per-call provider options. Extended thinking maps to the Anthropic `thinking`
 * field; through OpenRouter this is forwarded to the model's unified reasoning
 * where supported. Returns `undefined` when thinking is off so the OFF arm sends
 * nothing special (a clean comparison point with the other arms' OFF rows).
 */
export function providerOptions(cfg: ProviderConfig) {
  if (!cfg.thinking) return undefined;
  // Left un-annotated so TS infers a JSON-safe literal assignable to the SDK's
  // `providerOptions` (Record<string, JSONObject>). The Anthropic provider reads
  // `providerOptions.anthropic.thinking` and, through OpenRouter, forwards it to
  // the target model's unified reasoning where supported.
  return {
    anthropic: {
      thinking: { type: 'enabled', budgetTokens: cfg.thinkingTokens },
    },
  };
}
