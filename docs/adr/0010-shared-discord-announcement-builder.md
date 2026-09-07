# Consolidate Discord announcement formatting into one shared builder

Discord contest messages formatted inconsistently depending on which part of the system sent them: `lobby/formatting.py`, `completion_processor.py` (warning/live/completed and soft-finish), `notifications/bonus_announcements.py`, and inline formatting in `bot/discord_bot.py` each owned their own layout, so an emoji, a sheet link, or a bulleted-vs-flat structure could drift independently per call site.

`discord_announcements.py` now owns the shared chrome (sport emoji, header line, bulleted detail lines, inline sheet link) for all 6 push-notification kinds — contest-warning, live, completed, soft-finish, bonus-achievement, double-up-found — via one `build_*` function per kind. Each builder accepts only the fields relevant to its kind (bonus-achievement has no sheet link or entry fee; double-up-found has no relative-time field); nothing is forced to emit a placeholder for a field it doesn't have. `DISCORD_ROLE_MAP` and the canonical `SPORT_EMOJI` table relocate here too, alongside the chrome that reads them, rather than staying isolated in their own modules (`discord_roles.py`, and duplicated copies in `bot/discord_bot.py` and `cli/update_contests.py`).

The double-up-found builder keeps its existing gate, unchanged: a sport absent from `DISCORD_ROLE_MAP` gets no announcement sent at all, not just a missing role mention. This was confirmed during design to be intentional, existing scope — not a bug to fix.

Existing milestone wording (`"Contest starting soon (Nm)"`, `"Contest started"`, `"Contest ended"`, soft-finish's `"(updated)"` marker) is preserved verbatim; `CompletionProcessor`'s formatting methods now delegate to the shared builder instead of assembling text inline. Bonus-achievement and double-up-found messages were not under a wording-preservation constraint and were reformatted to use the same header/chrome style as the other four kinds (previously flat one-liners with no sport emoji).

The interactive bot commands (`!contests`, `!live`, `!upcoming`) keep their own terser, synchronous-reply format — they are not broadcast announcements — but now pull `sport_emoji`/`sheet_link` from the shared module instead of a second, independently-maintained copy.

Named `discord_announcements.py` rather than a `discord/` package, deliberately deviating from the module name proposed during design: `tests/conftest.py` puts `src/dk_results` directly on `sys.path`, so a same-named `discord` package there would shadow the real, pip-installed `discord.py` library that `bot/discord_bot.py` imports (`import discord`, `from discord.ext import commands`). A flat module avoids the collision without changing the seam.

Out of scope, per the originating spec: `DiscordRest`/`WebhookSender` transport behavior (chunking, retries, bot-token vs. webhook), and the pre-existing duplicate `0009-*` ADR numbering collision (unrelated, not fixed here).
