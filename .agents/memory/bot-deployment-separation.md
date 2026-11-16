---
name: Bot deployment separation
description: User's chosen boundary for always-on Telegram bot hosting.
---

Prepare the Telegram bot for a separate Repl, not a combined deployment with the shared API server.

**Why:** The user selected “Separate bot Repl (recommended)” when offered separate or combined hosting.

**How to apply:** Preserve the existing API deployment while preparing the bot's standalone hosting. Do not publish or stop the existing bot merely to prepare the separate project.
