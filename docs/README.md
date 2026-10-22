# Índice da documentação

| Documento | Descrição |
|---|---|
| [ROADMAP_IMPLEMENTACAO.md](ROADMAP_IMPLEMENTACAO.md) | Roadmap técnico F0–F6 do repositório |
| [DECISOES.md](DECISOES.md) | Registro de decisões arquiteturais (ADR simplificado) |
| [adr/ADR-006-correspondencia-de-fases.md](adr/ADR-006-correspondencia-de-fases.md) | Correspondência entre as fases F0–F7 do PDF e F0–F6 do roadmap técnico |
| [FONTES_E_IMPORTACAO.md](FONTES_E_IMPORTACAO.md) | Fontes de referência e regras de importação |
| [HANDOFF_CLAUDE.md](HANDOFF_CLAUDE.md) | Instruções de início para o Claude Code |
| [references/Plano_Ecossistema_Agentes_IA_2026.pdf](references/Plano_Ecossistema_Agentes_IA_2026.pdf) | Plano original (PDF, 17 páginas), preservado sem alterações |
| [security/Roadmap_Seguranca_Geral_v3.md](security/Roadmap_Seguranca_Geral_v3.md) | Roadmap de segurança geral e reutilizável (SEC-00 a SEC-42), preservado sem alterações |
| [CHECKSUMS.sha256](CHECKSUMS.sha256) | SHA-256 dos documentos importados |

## Verificar integridade

```bash
cd docs && sha256sum -c CHECKSUMS.sha256
```

Os documentos importados são cópias fiéis; não editá-los. Alterações entram em novos documentos ou em nova versão, com novo checksum.
