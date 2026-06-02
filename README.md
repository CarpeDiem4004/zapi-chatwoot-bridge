# zapi-chatwoot-bridge

Middleware Flask que conecta Z-API ↔ Chatwoot.

## Como funciona

```
Motorista → WhatsApp → Z-API → /webhook/zapi → Chatwoot (cria conversa)
Atendente → Chatwoot → /webhook/chatwoot → Z-API → WhatsApp → Motorista
```

## Deploy no Railway

1. Sobe esse repositório no GitHub
2. No Railway: New Project → Deploy from GitHub
3. Configura as variáveis de ambiente:

| Variável | Valor |
|---|---|
| CHATWOOT_URL | https://chatwoot-production-445d.up.railway.app |
| CHATWOOT_TOKEN | eYrrg4RDsWTZosHYv5HnALJH |
| CHATWOOT_ACCOUNT | 1 |
| CHATWOOT_INBOX | 1 |
| ZAPI_INSTANCE | 3F40BC4189F1C1E576D196BA8C2A7842 |
| ZAPI_TOKEN | E7B20D229EA5F9EBEB2A6C48 |

## Endpoints

- `POST /webhook/zapi` → recebe mensagens da Z-API
- `POST /webhook/chatwoot` → recebe respostas do Chatwoot
- `GET /health` → health check

## Configuração pós-deploy

### Na Z-API:
- Ao receber: `https://SEU-BRIDGE.railway.app/webhook/zapi`
- Ao enviar: deixar vazio

### No Chatwoot:
- Configurações → Integrações → Webhooks
- URL: `https://SEU-BRIDGE.railway.app/webhook/chatwoot`
- Eventos: message_created
