# web/ — the comparison UI

A single, self-contained static page ([`index.html`](index.html)) that presents the
three-way substrate comparison and the frozen-holdout results table. No build
step, no framework, no external requests — it inlines its own CSS and data and is
theme-aware (light/dark).

**Live:** https://claims-audit-agent.vercel.app

The numbers on the page are the same ones in the root [`README.md`](../README.md)
results table, which are in turn backed by the committed artifacts under
[`../agent_aisdk/artifacts/`](../agent_aisdk/artifacts/).

## Deploy

It deploys to Vercel as a static site (framework auto-detected as "Other"):

```bash
cd web
npx vercel deploy --prod        # first run links/creates the project
```

Or point a Vercel project's **Root Directory** at `web/` and every push redeploys.
Because it is a single static file, there is nothing to install or build.
