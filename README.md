# EnigmaTech Inspection Bot

Telegram bot that collects construction-site photos, voice recordings, and text
notes, then creates a Hebrew inspection report as a right-to-left Word document.

## Run

The bot runs as a persistent console workflow. It uses the Replit Secrets
`TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY`.

To start it from a shell:

```sh
PYTHONPATH=src python -m enigmatech_inspection_bot.bot
```

The bot retains pending Telegram updates on startup and reconnects after polling
network errors. Reports use `gemini-3.8-flash`; if that model is unavailable, the
bot discovers another available Flash model and excludes deprecated Gemini 2.5
Flash models.

## Use

- Send photos, voice notes, audio files, or text notes to the bot.
- Send `/report` to create and receive the Word report.
- Send `/clear` to delete the current chat's saved materials.
- Send `/help` for the Hebrew command guide.

Accepted notes and media are journaled in the private `.bot-state/` directory
(`BOT_STATE_DIR` can override it). They survive a **process restart on the same
filesystem**. After Telegram accepts the report, or when `/clear` is used, the
bot deletes the local files and journal. Corrupt journals are left untouched
and stop startup rather than silently discarding materials. Interrupted reports
can be retried with `/report` after restart.

This is **not** durable storage across VM replacement, redeploy, or migration
from the workspace to production. Finish all inspections before those actions.
The previous in-memory-only bot cannot retroactively journal its existing
sessions: finish those reports **before merging/restarting the old version**.

## Faster reports

- Up to three media uploads/preparation operations run concurrently per report.
- Photo and recording numbering stays in the original order.
- At most two reports run concurrently; excess requests get a Hebrew busy
  response without losing their materials.
- The Telegram status message updates every 15 seconds with the current stage
  and elapsed time. A status-message failure does not cancel a report.
- Safe timing logs cover media preparation, model generation, remote cleanup,
  Word creation, Telegram delivery, and total time, without logging content.
- The model and report length allowance are unchanged to avoid silently
  sacrificing inspection quality. Gemini generation can still take minutes.

## Reserved VM publishing

The project now includes a small operating-guide web app (`artifacts/bot-console`)
so it can be published. Its connectivity indicator checks the **API only**,
not Telegram or Gemini; it exposes no inspection data.

The project target is `vm`. The API artifact's production build runs
`bash scripts/build-production.sh`; its production command is
`python scripts/supervise_services.py`.

The build exports hash-locked Python dependencies into `.bot-runtime/`, builds
the existing Node API, and checks imports without starting the bot. Runtime
starts both the unchanged API and one Telegram worker. The supervisor restarts
a crashed worker with bounded exponential backoff (five retries per crash loop),
handles shutdown signals, and terminates the service if the API exits. A Telegram
polling conflict exits explicitly rather than repeatedly fighting another poller.
Reserved VM hosting is not an absolute uptime guarantee.

### Safe cutover (owner confirmation required)

1. Finish existing reports **before merging or restarting** the old bot. Do not
   use `/clear` unless you intend to delete the materials.
2. Merge this preparation. In Publishing, confirm **Reserved VM**, one instance,
   the EnigmaTech Bot web app and the API service, and the compute cost.
3. Confirm `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` exist in the production
   Secrets settings. Do not paste them into code/chat. No routine rotation is
   needed just to publish.
4. Stop the **EnigmaTech Telegram Bot** workspace workflow before publishing.
   Do not run a second poller with the same token anywhere else, including
   another workspace or overlapping deployment. The local lock cannot protect
   against a poller on another VM.
5. The owner clicks Publish. Check the deployment logs for startup and send
   `/help` in Telegram, then try a small report. An HTTP health response alone
   does not prove the bot is working.
6. Leave the workspace bot stopped while production runs. Before any later
   republish, finish outstanding reports and avoid overlapping pollers.

Nothing is published by these build scripts, tests, or the web page.

## Checks

```sh
python -m unittest discover -s tests
```

Offline production verification (does **not** start a Telegram poller):

```sh
bash scripts/build-production.sh
python scripts/supervise_services.py --check
pnpm run typecheck
```

Supervisor tests launch only short-lived fixture processes. Telegram/Gemini
pipeline tests use mocks, not live credentials or external API calls.
