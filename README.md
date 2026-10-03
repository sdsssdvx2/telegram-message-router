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

The workflow is intended to run every 5 minutes, which is the shortest interval supported by GitHub Actions scheduled workflows.

It can also be started manually from the Actions tab.
