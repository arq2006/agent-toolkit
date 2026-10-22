# Mapa de dados — modelo

Preencher **antes** de gerar ou revisar qualquer política de privacidade (PDF-F3). Consentimento não é a única base legal e não deve ser usado por reflexo. Cada projeto preenche a sua cópia **fora deste repositório**; nunca registrar dados pessoais reais aqui.

## Campos por tratamento de dados (uma linha por fluxo)

| Campo | Descrição |
|---|---|
| Dado coletado | Categoria (ex.: contato, mídia, identificador online, cobrança, prompts e transcrições enviados a IA) |
| Finalidade | Para que o dado é usado |
| Hipótese legal | Base legal da LGPD aplicável e justificativa |
| Titular | Quem é a pessoa (cliente, convidado, criança, funcionário...) |
| Origem | Como e onde o dado entra |
| Terceiros | Operadores e compartilhamentos (nuvem, pagamentos, analytics, provedores de IA) |
| Retenção | Prazo e critério |
| Descarte | Como e quando exclui, inclusive caches, derivados e backups |
| Acesso | Quem e quais papéis acessam |
| Incidentes | Plano de resposta e comunicação |
| Transferência internacional | Países e mecanismo, se houver |
| Canal do titular | Como exercer direitos |

## Modelo (YAML, dados fictícios)

```yaml
data_map_version: 1
project: "<nome-do-projeto>"
reviewed_at: "AAAA-MM-DD"
flows:
  - id: DM-001
    data: "e-mail do usuário (exemplo)"
    purpose: "autenticação e avisos do serviço"
    legal_basis: "execução de contrato (a confirmar por revisão jurídica)"
    data_subject: "usuário"
    origin: "formulário de cadastro"
    third_parties: ["<provedor-de-e-mail>"]
    retention: "enquanto a conta existir + <prazo>"
    disposal: "exclusão na conta, propagada a derivados e backups"
    access: ["suporte", "administrador"]
    incident_plan: "<referência>"
    international_transfer: "sim/não: <detalhe>"
    data_subject_channel: "<canal>"
```

Referência técnica de apoio: SEC-25 do [roadmap de segurança](../security/Roadmap_Seguranca_Geral_v3.md) (inventário e auditoria técnica de dados pessoais).
