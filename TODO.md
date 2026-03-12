# TODO

- [x] Fix `CallbackQuery` bot access bug in `handlers/agent_handler.py` (`query.bot` -> context bot).
- [x] Add safe delete wrappers to reduce expected Telegram 400 noise in logs.
- [x] Update conversation handler settings in `handlers/agent_handler.py` and `handlers/report_handler.py` to remove PTB warnings.
- [x] Add global PTB error handler in `bot.py` for cleaner exception logging.
- [ ] Run quick static verification via search and summarize final fixes.
