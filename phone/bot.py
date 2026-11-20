"""PHONE CONTROL: talk to your laptop agent from your phone, through a Telegram bot.

You message the bot; the agent runs on the laptop; the answer (and any file you asked
for) comes back to your phone. It is just another "shell" around the same
AgentSession the terminal and the porcupine use.

SECURITY - this lets someone drive your laptop, so it is locked down:
  * Only YOUR numeric Telegram user id(s) are accepted (TELEGRAM_ALLOWED_USER_IDS).
    Everyone else gets NO reply at all (the bot looks dead), and the attempt is logged.
  * Only private chats. Group messages are ignored.
  * Optional PIN (PHONE_PIN): you must send /unlock <pin> first. 3 wrong tries lock it for 15 minutes.
    The bot also deletes your /unlock message from the chat.
  * Risky actions (send, close, delete, terminal...) ASK YOU yes/no on the phone first.
  * Files: only documents/images/media/zip inside the allowed folders, max 45 MB (see agent/phone_bridge.py).
  * The bot token is read from .env and is never written to any log.
"""

import hmac
import time
from pathlib import Path

import httpx

from agent import activity_log, phone_bridge
from agent.phone_bridge import PHONE_PREFIX

TELEGRAM_LIMIT = 4000     # Telegram refuses messages longer than 4096 characters

HELP = (
    "I run on your laptop. Just tell me what to do.\n"
    "/status  - are you unlocked? is the laptop agent alive?\n"
    "/new     - start a fresh conversation\n"
    "/lock    - lock me now (needs /unlock <pin> again)\n"
    "Ask me for a file (\"send me my 363 assignment pdf\") and I will send it here."
)


class PhoneBot:
    UNLOCK_SECONDS = 3600        # after /unlock the bot stays open for an hour
    MAX_PIN_TRIES = 3
    LOCKOUT_SECONDS = 900        # 15 minutes
    ASK_TIMEOUT = 600            # how long to wait for your answer to a question

    def __init__(self, session, token: str, allowed_ids: set[int], pin: str = "",
                 api_base: str = "https://api.telegram.org", poll_timeout: int = 25, log=print) -> None:
        self.session = session
        self.token = token
        self.allowed = set(allowed_ids)
        self.pin = pin
        self.api_base = api_base.rstrip("/")
        self.poll_timeout = poll_timeout
        self.log = log
        self.http = httpx.Client(timeout=poll_timeout + 20)
        self.offset = 0                  # Telegram sends each update once we confirm the previous one
        self.unlocked_until = 0.0
        self.pin_failures = 0
        self.locked_out_until = 0.0

    # ================================================================ talking to Telegram
    def _safe(self, error: Exception) -> str:
        """An error message that can never contain the bot token (it is part of every URL)."""
        return f"{type(error).__name__}: {str(error).replace(self.token, '***')}"

    def _api(self, method: str, data: dict | None = None, files: dict | None = None) -> dict:
        url = f"{self.api_base}/bot{self.token}/{method}"
        if files:
            response = self.http.post(url, data=data, files=files)
        else:
            response = self.http.post(url, json=data or {})
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram refused {method}: {payload.get('description')}")
        return payload.get("result")

    def _get_updates(self, timeout: int) -> list[dict]:
        """Wait up to `timeout` seconds for new messages and mark them as received."""
        updates = self._api("getUpdates", {"offset": self.offset, "timeout": timeout,
                                           "allowed_updates": ["message"]}) or []
        for update in updates:
            self.offset = update["update_id"] + 1       # confirm: this one is never delivered again
        return updates

    def _send(self, chat_id: int, text: str) -> None:
        self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def _send_long(self, chat_id: int, text: str) -> None:
        """Send text, cut into pieces that fit Telegram's size limit (preferably at line breaks)."""
        text = text.strip() or "(done)"
        while text:
            if len(text) <= TELEGRAM_LIMIT:
                self._send(chat_id, text)
                return
            cut = text.rfind("\n", 0, TELEGRAM_LIMIT)
            cut = cut if cut > TELEGRAM_LIMIT // 2 else TELEGRAM_LIMIT
            self._send(chat_id, text[:cut])
            text = text[cut:].lstrip()

    def _send_file(self, chat_id: int, path: str, caption: str) -> None:
        with open(path, "rb") as handle:
            self._api("sendDocument", data={"chat_id": chat_id, "caption": caption[:1000]},
                      files={"document": (Path(path).name, handle)})

    # ================================================================ who is allowed to talk to me?
    def _note(self, text: str) -> None:
        """Print and write to the activity diary."""
        self.log(f"[phone] {text}")
        activity_log.note(f"PHONE: {text}")

    def _allowed_private_text(self, update: dict) -> tuple[int, str, int] | None:
        """Return (chat_id, text, message_id) if this is a text message from YOU in a private chat, else None.

        Strangers are never answered - only logged.
        """
        message = update.get("message")
        if not message or "text" not in message:
            return None
        user_id = (message.get("from") or {}).get("id")
        if message.get("chat", {}).get("type") != "private":
            self._note(f"ignored a message from a non-private chat (user id {user_id})")
            return None
        if user_id not in self.allowed:
            self._note(f"BLOCKED a message from unknown user id {user_id}")
            return None
        return message["chat"]["id"], message["text"].strip(), message["message_id"]

    # ================================================================ the main loop
    def run_forever(self, stop=None) -> None:
        """Listen for messages until `stop` (a threading.Event) is set or you press Ctrl+C."""
        self._note("phone bot is running")
        while not (stop and stop.is_set()):
            try:
                for update in self._get_updates(self.poll_timeout):
                    self._handle(update)
            except Exception as error:                # network hiccup: wait a little and carry on
                message = self._safe(error)
                if "Conflict" in message:             # Telegram lets only ONE program listen to a bot
                    self.log("[phone] another copy of this bot is already listening - waiting for it to stop")
                    time.sleep(10)
                else:
                    self.log(f"[phone] connection problem ({message}) - retrying")
                    time.sleep(3)

    def _handle(self, update: dict) -> None:
        found = self._allowed_private_text(update)
        if found is None:
            return
        chat_id, text, message_id = found
        now = time.time()

        if now < self.locked_out_until:                # too many wrong PINs: stay silent
            return
        if text.lower().startswith("/unlock"):
            self._unlock(chat_id, text, message_id)
            return
        if self.pin and now >= self.unlocked_until:
            self._send(chat_id, "Locked. Send /unlock followed by your PIN, e.g.  /unlock 1234")
            return

        command = text.lower().split()[0] if text.startswith("/") else ""
        if command in ("/start", "/help"):
            self._send(chat_id, HELP)
        elif command == "/status":
            state = "unlocked" if (not self.pin or now < self.unlocked_until) else "locked"
            self._send(chat_id, f"The laptop agent is online ({state}).")
        elif command == "/new":
            self.session.reset()
            self._send(chat_id, "Fresh conversation started.")
        elif command == "/lock":
            self.unlocked_until = 0.0
            self._send(chat_id, "Locked.")
        else:
            try:
                self._run_request(chat_id, text)
            except Exception as error:
                self._send(chat_id, f"Something went wrong: {self._safe(error)}")

    def _unlock(self, chat_id: int, text: str, message_id: int) -> None:
        if not self.pin:
            self._send(chat_id, "No PIN is set - you are already in.")
            return
        given = text[len("/unlock"):].strip()
        try:                                           # remove the PIN from the chat history (best effort)
            self._api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except Exception:
            pass
        if hmac.compare_digest(given.encode(), self.pin.encode()):     # constant-time comparison
            self.unlocked_until = time.time() + self.UNLOCK_SECONDS
            self.pin_failures = 0
            self._send(chat_id, f"Unlocked for {self.UNLOCK_SECONDS // 60} minutes.")
            return
        self.pin_failures += 1
        self._note(f"wrong PIN attempt ({self.pin_failures}/{self.MAX_PIN_TRIES})")
        if self.pin_failures >= self.MAX_PIN_TRIES:
            self.locked_out_until = time.time() + self.LOCKOUT_SECONDS
            self.pin_failures = 0
            self._send(chat_id, f"Too many wrong PINs. Locked for {self.LOCKOUT_SECONDS // 60} minutes.")
        else:
            self._send(chat_id, "Wrong PIN.")

    # ================================================================ running a request
    def _run_request(self, chat_id: int, text: str) -> None:
        self._api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        phone_bridge.begin()                           # lets the agent queue files for this request
        try:
            reply = self.session.run(PHONE_PREFIX + text[:2000],
                                     ask=lambda question: self._ask(chat_id, question))
        finally:
            files = phone_bridge.end()
        self._send_long(chat_id, reply)
        for path, caption in files:
            try:
                self._send_file(chat_id, path, caption)
            except Exception as error:
                self._send(chat_id, f"I could not send {Path(path).name}: {self._safe(error)}")

    def _ask(self, chat_id: int, question: str) -> str:
        """The agent has a question (or wants a yes/no): send it and wait for YOUR next message."""
        self._send_long(chat_id, f"? {question}")
        deadline = time.time() + self.ASK_TIMEOUT
        while time.time() < deadline:
            for update in self._get_updates(self.poll_timeout):
                found = self._allowed_private_text(update)
                if found is not None:
                    return found[1]
        self._send(chat_id, "No answer - I'll carry on without one.")
        return "(no answer)"


def whoami(token: str, api_base: str = "https://api.telegram.org", seconds: float | None = None, log=print) -> None:
    """Find out YOUR numeric Telegram id: message the bot, and the id is printed here.

    It never replies to anyone, so it is safe to run before an allow-list exists.
    """
    bot = PhoneBot(None, token, set(), api_base=api_base, poll_timeout=5, log=log)
    end = time.time() + seconds if seconds else None
    log("Waiting for a message to the bot... (press Ctrl+C to stop)")
    while end is None or time.time() < end:
        for update in bot._get_updates(5):
            message = update.get("message") or {}
            sender = message.get("from") or {}
            if sender:
                log(f"  user id {sender.get('id')}  name {sender.get('first_name', '')} "
                    f"@{sender.get('username', '-')}   <- put this id in TELEGRAM_ALLOWED_USER_IDS")
