# ADR-006 — Correspondência entre as fases do PDF (F0–F7) e do roadmap técnico (F0–F6)

**Status:** proposta (aguarda revisão humana)
**Data:** 22/10/2026

## Contexto
O plano original em PDF ([references/Plano_Ecossistema_Agentes_IA_2026.pdf](../references/Plano_Ecossistema_Agentes_IA_2026.pdf), seção 14) define as fases F0–F7. O [ROADMAP_IMPLEMENTACAO.md](../ROADMAP_IMPLEMENTACAO.md) usa F0–F6, com agrupamento e ordem diferentes. As duas numerações coexistem; sem uma tabela de correspondência, o mesmo rótulo (por exemplo, "F2") designa coisas distintas.

Outras divergências identificadas: o PDF fala em repositório privado e no nome `ai-agent-toolkit`; a decisão vigente é repositório **público** chamado `agent-toolkit` (o nome do PDF era uma proposta anterior).

## Decisão
1. Os dois documentos são preservados integralmente; nenhuma funcionalidade de qualquer um deles é eliminada.
2. Nos textos novos, as fases são citadas com prefixo: **PDF-Fn** para o PDF e **GH-Fn** para o roadmap técnico do repositório.
3. A tabela abaixo é a referência de correspondência. Reconciliação adicional (inclusive a numeração única futura) fica para a tarefa F0.2.
4. Nome canônico: `agent-toolkit`. Visibilidade: pública.

## Tabela de correspondência

| Fase do PDF | Entregáveis no PDF | Fase GH correspondente | Observação |
|---|---|---|---|
| PDF-F0 Núcleo | Políticas, inventário de ferramentas, matriz de risco, zero mudanças em projetos (o PDF diz "repo privado") | GH-F0 | Visibilidade agora pública; inventário e matriz de risco ainda não têm tarefa explícita no GH-F0 |
| PDF-F1 Claude | 2–3 agentes (planejador, implementador, auditor), skills, hooks, simulação em sandbox | GH-F1 (agentes) e GH-F2 (skills) | Hooks e repositório sandbox não aparecem explicitamente no GH |
| PDF-F2 Operação multiagente | Worktrees, reserva de arquivo, relato de evidências, integração por PR manual | GH-F1 (contrato de tarefa) | Coberto parcialmente; ver regras transversais do GH |
| PDF-F3 Compliance | Checklist de 17 itens, mapa de dados, fontes oficiais, relatório por projeto | GH-F2 (guardrails e checklists derivados do roadmap de segurança) | **Lacuna:** o GH não cita explicitamente checklist de 17 itens, mapa de dados e relatório; tratar em F0.2 sem remover nada |
| PDF-F4 Hermes | Instalação isolada, texto, memória limitada, voz, automações só de leitura | GH-F4 | Equivalente |
| PDF-F5 Ferramentas/IA | MCP próprio e Media Lab (STT/TTS/imagem/vídeo), métricas e segurança | GH-F3 (MCP e adaptadores) e GH-F4 (multimodalidade) | Dividido em duas fases no GH |
| PDF-F6 FreeLLMAPI | Benchmark local, consentimento para roteamento, custo versus qualidade | GH-F5 | Equivalente (GH-F5 inclui economia de tokens e modelos) |
| PDF-F7 WhatsApp | Piloto com API oficial, handoff humano, proteção de dados | GH-F6 | Equivalente |

Em sentido inverso, todas as fases GH têm origem no PDF: GH-F0 ← PDF-F0; GH-F1 ← PDF-F1/F2; GH-F2 ← PDF-F1/F3; GH-F3 ← PDF-F5; GH-F4 ← PDF-F4/F5; GH-F5 ← PDF-F6; GH-F6 ← PDF-F7.

## Roadmap de segurança
O [Roadmap_Seguranca_Geral_v3.md](../security/Roadmap_Seguranca_Geral_v3.md) (SEC-00 a SEC-42) é um modelo mestre independente de tecnologia: o próprio texto afirma que exemplos de tecnologias são ilustrativos e não componentes presumidos. É a base dos controles de GH-F2 e das demais fases; a aplicabilidade é decidida por projeto.

## Consequências
- Leitores conseguem relacionar os dois documentos sem editar nenhum deles.
- A lacuna de compliance (PDF-F3) fica registrada como pendência da F0.2.
- Estrutura de pastas (PDF: `agents/`, `skills/`, `policies/`, `workflows/`, `adapters/` versus README: `.claude/`, `src/`, `integrations/`) permanece em aberto para a F0.2.
