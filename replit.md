# EnigmaTech Inspection Bot

Telegram bot that turns construction-site photos, recordings, and notes into a Hebrew RTL Word inspection report.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `PYTHONPATH=src python -m enigmatech_inspection_bot.bot` — run the Telegram bot
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required secrets: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`
- Optional environment: `BOT_TIMEZONE` (defaults to `Asia/Jerusalem`), `LOG_LEVEL` (defaults to `INFO`)

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- Python 3.12, python-telegram-bot, Google GenAI SDK, python-docx
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `src/enigmatech_inspection_bot/` — Telegram handlers, chat sessions, Gemini processing, and Word report generation
- `tests/` — Python unit tests for model fallback and RTL report formatting
- `pyproject.toml` and `uv.lock` — Python dependencies and lockfile

## Architecture decisions

- Keep each chat's media session in memory, as requested; a bot restart clears unfinished sessions.
- Upload media to Gemini's Files API for multimodal processing, then delete uploaded copies after report generation.
- Prefer `gemini-3.8-flash`; discover an available Flash model only if needed, excluding deprecated Gemini 2.5 Flash models.

## Product

- `/start` and `/help` explain how to submit photos, audio, and notes in Hebrew.
- `/report` produces a Hebrew inspection report with a photo appendix in a properly formatted RTL `.docx`.
- `/clear` deletes the chat's saved media and notes.

## User preferences

- Use Hebrew for bot replies and the generated inspection report.

## Gotchas

- Keep the Gemini model fallback away from deprecated Gemini 2.5 Flash variants.
- Local files are temporary and should be removed after successful delivery or `/clear`.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
