import os
import requests
from requests.adapters import HTTPAdapter
from flask import Flask, request, jsonify

app = Flask(__name__)

CHATWOOT_URL     = os.environ.get("CHATWOOT_URL", "https://chatwoot-production-445d.up.railway.app")
CHATWOOT_TOKEN   = os.environ.get("CHATWOOT_TOKEN", "eYrrg4RDsWTZosHYv5HnALJH")
CHATWOOT_ACCOUNT = os.environ.get("CHATWOOT_ACCOUNT", "1")
CHATWOOT_INBOX   = os.environ.get("CHATWOOT_INBOX", "1")

ZAPI_INSTANCE    = os.environ.get("ZAPI_INSTANCE", "3F40BC4189F1C1E576D196BA8C2A7842")
ZAPI_TOKEN       = os.environ.get("ZAPI_TOKEN", "E7B20D229EA5F9EBEB2A6C48")
ZAPI_URL         = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}"

HEADERS = {
    "api_access_token": CHATWOOT_TOKEN,
    "Content-Type": "application/json",
    "Connection": "close"
}

BASE = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT}"

last_payloads = {"zapi": {}, "chatwoot": {}}


def cw_get(url, **kwargs):
    """GET pro Chatwoot com sessão nova a cada chamada"""
    s = requests.Session()
    s.headers.update({"Connection": "close"})
    return s.get(url, headers=HEADERS, timeout=15, **kwargs)


def cw_post(url, **kwargs):
    """POST pro Chatwoot com sessão nova a cada chamada"""
    s = requests.Session()
    s.headers.update({"Connection": "close"})
    return s.post(url, headers=HEADERS, timeout=15, **kwargs)


@app.route("/webhook/zapi", methods=["POST"])
def zapi_webhook():
    data = request.json or {}
    last_payloads["zapi"] = data

    if data.get("fromMe") or not data.get("phone"):
        return jsonify({"status": "ignored"}), 200

    phone = data.get("phone", "").replace("+", "").replace(" ", "").replace("-", "")
    name  = data.get("senderName") or data.get("pushName") or phone
    text  = ""

    msg_type = data.get("type", "")
    if msg_type == "ReceivedCallback":
        t = data.get("text", "")
        text = t.get("message", "") if isinstance(t, dict) else str(t)
    elif msg_type in ["AudioCallback", "VideoCallback", "ImageCallback", "DocumentCallback"]:
        text = f"[{msg_type.replace('Callback','')} recebido]"
    else:
        text = str(data.get("text", "") or data.get("body", "") or "")

    if not text:
        return jsonify({"status": "no_text"}), 200

    contact_id = get_or_create_contact(phone, name)
    if not contact_id:
        return jsonify({"status": "error", "msg": "contact failed"}), 500

    conversation_id = get_or_create_conversation(contact_id, phone)
    if not conversation_id:
        return jsonify({"status": "error", "msg": "conversation failed"}), 500

    send_message_to_chatwoot(conversation_id, text, incoming=True)
    return jsonify({"status": "ok"}), 200


@app.route("/webhook/chatwoot", methods=["POST"])
def chatwoot_webhook():
    data = request.json or {}
    last_payloads["chatwoot"] = data

    if data.get("event") != "message_created":
        return jsonify({"status": "ignored"}), 200

    if data.get("message_type") != "outgoing":
        return jsonify({"status": "ignored"}), 200

    if data.get("private"):
        return jsonify({"status": "ignored_private"}), 200

    content = data.get("content", "")
    if not content:
        return jsonify({"status": "no_content"}), 200

    phone = ""

    # 1. conversation.additional_attributes.phone
    conversation = data.get("conversation", {})
    phone = conversation.get("additional_attributes", {}).get("phone", "")

    # 2. meta.sender (contato)
    if not phone:
        meta = conversation.get("meta", {})
        sender = meta.get("sender", {})
        if sender.get("type") == "contact":
            phone = sender.get("phone_number") or sender.get("identifier") or ""

    # 3. via API
    if not phone:
        conv_id = conversation.get("id")
        if conv_id:
            phone = get_phone_from_conversation(conv_id)

    phone = str(phone).replace("+", "").replace(" ", "").replace("-", "").strip()

    if not phone or len(phone) < 8:
        return jsonify({"status": "no_phone"}), 200

    resp = requests.post(f"{ZAPI_URL}/send-text", json={
        "phone": phone,
        "message": content
    }, timeout=15)

    return jsonify({
        "status": "sent",
        "phone": phone,
        "zapi_status": resp.status_code,
        "zapi_response": resp.text
    }), 200


@app.route("/debug/last", methods=["GET"])
def debug_last():
    return jsonify(last_payloads), 200

@app.route("/debug/chatwoot", methods=["GET"])
def debug_chatwoot():
    return jsonify(last_payloads["chatwoot"]), 200


def get_phone_from_conversation(conv_id):
    try:
        r = cw_get(f"{BASE}/conversations/{conv_id}")
        if r.status_code == 200:
            conv = r.json()
            phone = conv.get("additional_attributes", {}).get("phone", "")
            if phone:
                return phone
            meta = conv.get("meta", {})
            sender = meta.get("sender", {})
            contact_id = sender.get("id")
            if contact_id:
                r2 = cw_get(f"{BASE}/contacts/{contact_id}")
                if r2.status_code == 200:
                    c = r2.json()
                    return c.get("phone_number") or c.get("identifier") or ""
    except Exception:
        pass
    return ""


def get_or_create_contact(phone, name):
    try:
        r = cw_get(f"{BASE}/contacts/search", params={"q": phone, "page": 1})
        if r.status_code == 200:
            results = r.json().get("payload", [])
            if results:
                return results[0]["id"]
    except Exception:
        pass

    try:
        r = cw_post(f"{BASE}/contacts", json={
            "name": name,
            "phone_number": f"+{phone}",
            "identifier": phone
        })
        if r.status_code in [200, 201]:
            return r.json().get("id")
    except Exception:
        pass
    return None


def get_or_create_conversation(contact_id, phone):
    try:
        r = cw_get(f"{BASE}/contacts/{contact_id}/conversations")
        if r.status_code == 200:
            for conv in r.json().get("payload", []):
                if (str(conv.get("inbox_id")) == str(CHATWOOT_INBOX) and
                        conv.get("status") == "open"):
                    return conv["id"]
    except Exception:
        pass

    try:
        r = cw_post(f"{BASE}/conversations", json={
            "inbox_id": int(CHATWOOT_INBOX),
            "contact_id": contact_id,
            "additional_attributes": {"phone": phone}
        })
        if r.status_code in [200, 201]:
            return r.json().get("id")
    except Exception:
        pass
    return None


def send_message_to_chatwoot(conversation_id, text, incoming=True):
    try:
        cw_post(
            f"{BASE}/conversations/{conversation_id}/messages",
            json={
                "content": text,
                "message_type": "incoming" if incoming else "outgoing",
                "private": False
            }
        )
    except Exception:
        pass


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bridge": "zapi-chatwoot"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
