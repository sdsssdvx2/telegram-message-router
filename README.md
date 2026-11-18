# Telegram Message Router

A small GitHub Actions workflow that periodically checks one Telegram chat and routes selected messages to two destination chats.

## Behavior

- Telegram documents/files are forwarded to the document destination.
- Plain text messages containing a URL are forwarded to the link destination.
- Photos, ordinary videos, GIFs, voice messages, video notes, stickers, and media captions are ignored.
- The last processed position is stored in the account's Saved Messages.
- Chat identifiers and the Telegram session are supplied only through GitHub Actions repository secrets.

## Required repository secrets

- `TG_SESSION_STRING`
- `SOURCE_CHAT_ID`
- `DOCUMENT_TARGET_CHAT_ID`
- `LINK_TARGET_CHAT_ID`

No real chat names, chat IDs, or Telegram session credentials are stored in this repository.

## Schedule

The router runs on an always-on server: with `ROUTER_LOOP_SECONDS=60` the script
stays connected and checks once a minute. Without that variable it checks once
and exits, which is what the manual GitHub Actions workflow does.

Do not run both at the same time with the same Telegram session.

## Long-term operation

A separate weekly keepalive workflow creates a tiny timestamp commit. This keeps
the public repository active so GitHub does not automatically disable scheduled
workflows after 60 days of repository inactivity.

The router itself remains independent of any personal computer. Rebooting or
turning off a local computer does not affect scheduled runs.
