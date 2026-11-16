---
name: Telegram token logging
description: Prevent Telegram Bot API credentials from appearing in polling logs.
---

The Telegram Bot API token is part of request URLs. Default HTTPX info logging can therefore expose it while `python-telegram-bot` polls or configures commands.

**Why:** Startup request logs included the full Bot API URL and exposed the configured token.

**How to apply:** In Telegram polling services, suppress HTTPX/HTTP Core request logs and avoid logging raw request exceptions or tracebacks that may include the URL.
