---
title: Retail CEO Office
emoji: 🏪
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Retail CEO Office — Hugging Face Space

This file holds the Hugging Face **Docker Space** configuration (the YAML
front-matter above). When deploying this project as a Space, copy this file to
`README.md` on the Space so the Hub picks up the `sdk: docker` / `app_port: 7860`
settings.

It is kept separate from the main project [`README.md`](./README.md) so that the
GitHub landing page renders cleanly (GitHub shows Space front-matter as literal
text at the top of the README).

The Space serves a live, CPU-only, key-free "Pixel CEO Office" dashboard: a
FastAPI backend ([`office_api/`](./office_api/)) streams a scripted `RetailCEOEnv`
episode into a React + PixiJS SPA ([`office/frontend/`](./office/frontend/)).
Container entry point is the [`Dockerfile`](./Dockerfile). See the
[Live Office Demo](./README.md#live-office-demo) section of the main README for
details.
