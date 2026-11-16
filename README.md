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

The bot drops pending Telegram updates on startup and reconnects after polling
network errors. Reports use `gemini-3.8-flash`; if that model is unavailable, the
bot discovers another available Flash model and excludes deprecated Gemini 2.5
Flash models.

## Use

- Send photos, voice notes, audio files, or text notes to the bot.
- Send `/report` to create and receive the Word report.
- Send `/clear` to delete the current chat's saved materials.
- Send `/help` for the Hebrew command guide.

Media files are kept in a temporary directory while a report is being prepared.
After a report is delivered, or when `/clear` is used, the bot deletes the local
files and the in-memory session. Sessions are intentionally in memory, so
restarting the bot clears unfinished sessions.

## Checks

```sh
python -m unittest discover -s tests
```
