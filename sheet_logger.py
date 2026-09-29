import os
import threading
import requests

WEBHOOK_URL = os.getenv("COMPLETION_WEBHOOK_URL")
WEBHOOK_TOKEN = os.getenv("COMPLETION_WEBHOOK_TOKEN")


def report_session(user_id, event, stage="", email=""):
    """event: 'start' | 'progress' | 'complete'. Fire-and-forget; never blocks or crashes a session."""
    if not WEBHOOK_URL:
        return
    payload = {
        "token": WEBHOOK_TOKEN,
        "participant_id": str(user_id),
        "event": event,
        "stage": stage,
        "email": email,
    }

    def _send():
        try:
            requests.post(WEBHOOK_URL, json=payload, timeout=10)
        except Exception as e:
            print(f"[completion-sheet] failed: {e}")

    threading.Thread(target=_send, daemon=True).start()