import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === CONFIGURAÇÕES ===
CHATWOOT_URL      = os.environ.get("CHATWOOT_URL", "https://chatwoot-production-445d.up.railway.app")
CHATWOOT_TOKEN    = os.environ.get("CHATWOOT_TOKEN", "eYrrg4RDsWTZosHYv5HnALJH")
CHATWOOT_ACCOUNT  = os.environ.get("CHATWOOT_ACCOUNT", "1")
CHATWOOT_INBOX    = os.environ.get("CHATWOOT_INBOX", "1")

ZAPI_INSTANCE     = os.environ.get("ZAPI_INSTANCE", "3F40BC4189F1C1E576D196BA8C2A7842")
ZAPI_TOKEN        = os.environ.get("ZAPI_TOKEN", "E7B20D229EA5F9EBEB2A6C48")
ZAPI_URL          = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}"

HEADERS = {
    "api_access_token": CHATWOOT_TOKEN,
    "Content-Type": "application/json"
}

BASE = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT}"

# ==========================================
# RECEBE MENSAGEM DA Z-API → ENVIA PRO CHATWOOT
# ==========================================
@app.route("/webhook/zapi", methods=["POST"])
def zapi_webhook():
    data = request.json or {}

    # Ignora eventos que não são mensagens recebidas
    if data.get("fromMe") or not data.get("phone"):
        return jsonify({"status": "ignored"}), 200

    phone   = data.get("phone", "").replace("+", "").replace(" ", "").replace("-", "")
    name    = data.get("senderName") or data.get("pushName") or phone
    text    = ""

    # Extrai o texto dependendo do tipo de mensagem
    msg_type = data.get("type", "")
    if msg_type == "ReceivedCallback":
        text = data.get("text", {}).get("message", "") if isinstance(data.get("text"), dict) else data.get("text", "")
    elif msg_type in ["AudioCallback", "VideoCallback", "ImageCallback", "DocumentCallback"]:
        text = f"[{msg_type.replace('Callback','')} recebido — não suportado em texto]"
    else:
        text = str(data.get("text", "") or data.get("body", "") or "")

    if not text:
        return jsonify({"status": "no_text"}), 200

    # 1. Busca ou cria contato no Chatwoot
    contact_id = get_or_create_contact(phone, name)
    if not contact_id:
        return jsonify({"status": "error", "msg": "contact creation failed"}), 500

    # 2. Busca conversa aberta ou cria nova
    conversation_id = get_or_create_conversation(contact_id, phone)
    if not conversation_id:
        return jsonify({"status": "error", "msg": "conversation creation failed"}), 500

    # 3. Envia a mensagem pra conversa
    send_message_to_chatwoot(conversation_id, text, incoming=True)

    return jsonify({"status": "ok"}), 200


# ==========================================
# RECEBE RESPOSTA DO CHATWOOT → ENVIA PRO ZAPI
# ==========================================
@app.route("/webhook/chatwoot", methods=["POST"])
def chatwoot_webhook():
    data = request.json or {}

    if data.get("event") != "message_created":
        return jsonify({"status": "ignored"}), 200

    msg = data.get("message_type")
    if msg != "outgoing":
        return jsonify({"status": "ignored"}), 200

    content = data.get("content", "")
    if not content:
        return jsonify({"status": "no_content"}), 200

    # Pega o número do contato da conversa
    conversation = data.get("conversation", {})
    meta = conversation.get("meta", {})
    sender = meta.get("sender", {})

    # O identificador do contato (source_id = phone)
    contact_identifier = sender.get("identifier") or sender.get("phone_number") or ""
    phone = contact_identifier.replace("+", "").replace(" ", "").replace("-", "")

    if not phone:
        return jsonify({"status": "no_phone"}), 200

    # Envia via Z-API
    resp = requests.post(f"{ZAPI_URL}/send-text", json={
        "phone": phone,
        "message": content
    })

    return jsonify({"status": "sent", "zapi": resp.status_code}), 200


# ==========================================
# HELPERS
# ==========================================
def get_or_create_contact(phone, name):
    # Busca por telefone
    r = requests.get(f"{BASE}/contacts/search", params={"q": phone, "page": 1}, headers=HEADERS)
    if r.status_code == 200:
        results = r.json().get("payload", [])
        if results:
            return results[0]["id"]

    # Cria se não existir
    r = requests.post(f"{BASE}/contacts", json={
        "name": name,
        "phone_number": f"+{phone}",
        "identifier": phone
    }, headers=HEADERS)

    if r.status_code in [200, 201]:
        return r.json().get("id")
    return None


def get_or_create_conversation(contact_id, phone):
    # Busca conversas abertas do contato nessa inbox
    r = requests.get(f"{BASE}/contacts/{contact_id}/conversations", headers=HEADERS)
    if r.status_code == 200:
        conversations = r.json().get("payload", [])
        for conv in conversations:
            if (str(conv.get("inbox_id")) == str(CHATWOOT_INBOX) and
                    conv.get("status") == "open"):
                return conv["id"]

    # Cria nova conversa
    r = requests.post(f"{BASE}/conversations", json={
        "inbox_id": int(CHATWOOT_INBOX),
        "contact_id": contact_id,
        "additional_attributes": {"phone": phone}
    }, headers=HEADERS)

    if r.status_code in [200, 201]:
        return r.json().get("id")
    return None


def send_message_to_chatwoot(conversation_id, text, incoming=True):
    requests.post(
        f"{BASE}/conversations/{conversation_id}/messages",
        json={
            "content": text,
            "message_type": "incoming" if incoming else "outgoing",
            "private": False
        },
        headers=HEADERS
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bridge": "zapi-chatwoot"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
