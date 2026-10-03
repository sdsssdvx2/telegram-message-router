import asyncio
import os
import re
import sys
from typing import Optional

from pyrogram import Client
from pyrogram.enums import MessageEntityType
from pyrogram.errors import FloodWait, RPCError


SESSION_STRING = os.environ["TG_SESSION_STRING"].strip()
SOURCE_CHAT_ID = int(os.environ["SOURCE_CHAT_ID"])
DOCUMENT_TARGET_CHAT_ID = int(os.environ["DOCUMENT_TARGET_CHAT_ID"])
LINK_TARGET_CHAT_ID = int(os.environ["LINK_TARGET_CHAT_ID"])

STATE_TAG = "telegram-message-router-state-v1"
URL_RE = re.compile(r"(?i)(?:https?://|www\.|t\.me/)\S+")

MAX_RETRIES = 5
MAX_FLOODWAIT_SECONDS = 240


def is_document(message) -> bool:
    return message.document is not None


def is_link_text(message) -> bool:
    if not message.text:
        return False

    if URL_RE.search(message.text):
        return True

    return any(
        entity.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK)
        for entity in (message.entities or [])
    )


def parse_state(text: str) -> Optional[tuple[int, int]]:
    # Also accepts an older checkpoint that may contain literal "\n" sequences.
    normalized = (text or "").replace("\\n", "\n")

    try:
        fields = dict(
            line.split("=", 1)
            for line in normalized.splitlines()
            if "=" in line
        )
        return int(fields["source_chat_id"]), int(fields["last_processed_id"])
    except (KeyError, TypeError, ValueError):
        return None


def state_text(last_processed_id: int) -> str:
    return (
        f"[{STATE_TAG}]\n"
        f"source_chat_id={SOURCE_CHAT_ID}\n"
        f"last_processed_id={last_processed_id}\n"
        "Checkpoint used by an automated Telegram message router."
    )


async def safe_forward(message, target_chat_id: int, label: str) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await message.forward(target_chat_id)
            print(f"[FORWARDED] {label}")
            return

        except FloodWait as exc:
            wait_seconds = int(exc.value) + 1
            if wait_seconds > MAX_FLOODWAIT_SECONDS:
                raise RuntimeError("Telegram rate limit is longer than this run can safely wait.") from exc

            print(f"[WAIT] Telegram rate limit: {wait_seconds}s")
            await asyncio.sleep(wait_seconds)

        except (OSError, TimeoutError):
            if attempt == MAX_RETRIES:
                raise

            delay = min(2 ** attempt, 30)
            print(f"[RETRY] Temporary network error; retrying in {delay}s")
            await asyncio.sleep(delay)

        except RPCError:
            raise


async def find_state_message(app: Client):
    candidates = []
    seen_ids = set()

    # Collect neutral and older compatible checkpoints without knowing or
    # publishing any previous tag/name. Only checkpoints for this exact source
    # ID are accepted.
    for query in (STATE_TAG, "source_chat_id"):
        async for msg in app.search_messages("me", query=query, limit=100):
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)

            parsed = parse_state(msg.text or "")
            if parsed and parsed[0] == SOURCE_CHAT_ID:
                candidates.append((parsed[1], msg))

    if not candidates:
        return None, None, False

    last_processed_id, message = max(candidates, key=lambda item: item[0])
    migrated = not (message.text or "").startswith(f"[{STATE_TAG}]")
    return message, last_processed_id, migrated


async def save_state(app: Client, state_message, last_processed_id: int):
    text = state_text(last_processed_id)

    if state_message is None:
        return await app.send_message("me", text)

    if state_message.text != text:
        await state_message.edit_text(text)

    return state_message


async def latest_source_id(app: Client) -> int:
    async for msg in app.get_chat_history(SOURCE_CHAT_ID, limit=1):
        return msg.id
    return 0


async def collect_pending(app: Client, last_processed_id: int):
    pending = []

    async for msg in app.get_chat_history(SOURCE_CHAT_ID):
        if msg.id <= last_processed_id:
            break
        pending.append(msg)

    pending.reverse()
    return pending


async def run_once() -> None:
    app = Client(
        "telegram_message_router_actions",
        session_string=SESSION_STRING,
        workers=1,
        no_updates=True,
    )

    async with app:
        state_message, last_processed_id, migrated = await find_state_message(app)

        if state_message is None:
            current_id = await latest_source_id(app)
            await save_state(app, None, current_id)
            print("[BOOTSTRAP] Checkpoint created at the current source position.")
            return

        if migrated:
            state_message = await save_state(app, state_message, last_processed_id)
            print("[MIGRATE] Existing compatible checkpoint adopted.")

        pending = await collect_pending(app, last_processed_id)

        if not pending:
            print("[IDLE] No new messages.")
            return

        print(f"[START] Checking {len(pending)} new message(s).")
        since_checkpoint = 0

        for msg in pending:
            forwarded = False

            if is_document(msg):
                await safe_forward(msg, DOCUMENT_TARGET_CHAT_ID, "document")
                forwarded = True
            elif is_link_text(msg):
                await safe_forward(msg, LINK_TARGET_CHAT_ID, "link")
                forwarded = True

            last_processed_id = msg.id
            since_checkpoint += 1

            if forwarded or since_checkpoint >= 50:
                state_message = await save_state(
                    app,
                    state_message,
                    last_processed_id,
                )
                since_checkpoint = 0

        await save_state(app, state_message, last_processed_id)
        print("[DONE] Checkpoint updated.")


if __name__ == "__main__":
    try:
        asyncio.run(run_once())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Do not print exception arguments: Telegram errors can contain
        # identifiers that should not appear in public Actions logs.
        print(f"[ERROR] Router run failed ({type(exc).__name__}).")
        raise SystemExit(1)
