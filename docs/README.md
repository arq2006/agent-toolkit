# Índice da documentação

| Documento | Descrição |
|---|---|
| [ROADMAP_IMPLEMENTACAO.md](ROADMAP_IMPLEMENTACAO.md) | Roadmap técnico GH-F0 a GH-F6 (referência operacional) |
| [ARQUITETURA.md](ARQUITETURA.md) | Arquitetura de diretórios alvo e mapa de reconciliação |
| [DECISOES.md](DECISOES.md) | Registro de decisões arquiteturais (ADR simplificado) |
| [adr/ADR-006-correspondencia-de-fases.md](adr/ADR-006-correspondencia-de-fases.md) | Correspondência entre PDF-F0–F7 e GH-F0–F6 |
| [adr/ADR-007-arquitetura-de-diretorios.md](adr/ADR-007-arquitetura-de-diretorios.md) | Decisão sobre a estrutura de diretórios |
| [adr/ADR-008-compliance-juridico-separado-do-tecnico.md](adr/ADR-008-compliance-juridico-separado-do-tecnico.md) | Decisão sobre compliance jurídico × auditoria técnica |
| [compliance/README.md](compliance/README.md) | Compliance: checklist de 17 itens, mapa de dados e relatório por projeto |
| [contratos/README.md](contratos/README.md) | Contratos de agente, skill e tarefa (GH-F1.1, integrados) |
| [materializacao-claude-code.md](materializacao-claude-code.md) | Procedimento e evidências da materialização em `.claude/agents/` (GH-F1.4) |
| [pesquisas/claude-code-materializacao-2026-10-22.md](pesquisas/claude-code-materializacao-2026-10-22.md) | Pesquisa da documentação do Claude Code (GH-F1.3) |
| [adr/ADR-010-materializacao-em-claude-code.md](adr/ADR-010-materializacao-em-claude-code.md) | Proposta de materialização em `.claude/` |
| [adr/ADR-011-isolamento-do-processo.md](adr/ADR-011-isolamento-do-processo.md) | Proposta de isolamento portátil do processo (GH-F1.8, provisório); não há STRONG demonstrado |
| [plans/GH-F1-8-readonly-executor-boundary.md](plans/GH-F1-8-readonly-executor-boundary.md) | Prototipo da interface read-only com JSON estrito e pathguard, nao ligado aos agentes |
| [plans/GH-F1-8-srt-readonly-synthetic-pilot.md](plans/GH-F1-8-srt-readonly-synthetic-pilot.md) | Piloto de integração sob SRT com fixture fictícia, sem Claude e sem autorização de execução de agentes |
| [plans/GH-F1-9-openat2-kernel-path-boundary.md](plans/GH-F1-9-openat2-kernel-path-boundary.md) | Experimento Linux openat2 contra symlinks/mount traversal, com canário SRT sintético e sem agentes |
| [plans/GH-F1-10-agent-task-policy-preview.md](plans/GH-F1-10-agent-task-policy-preview.md) | Pré-admissão de tarefas: escopo textual, local-first e revisão obrigatória antes de nuvem (sem execução de agentes) |
| [plans/GH-F1-11-offline-task-batch-preview.md](plans/GH-F1-11-offline-task-batch-preview.md) | Pré-coordenação de lotes fictícios, conflitos de arquivos e tags de worktree/branch; nenhuma execução de agentes |
| [plans/GH-F1-12-delegation-catalog-preview.md](plans/GH-F1-12-delegation-catalog-preview.md) | Catálogo simbólico dos 12 domínios e contratos de delegação hierárquica sem instalação ou execução de agentes |
| [plans/GH-F1-13-native-boundary-readiness.md](plans/GH-F1-13-native-boundary-readiness.md) | Gate de diagnóstico de hardlink nativo, bind mounts e concorrência: STRONG indisponível e agentes bloqueados |
| [plans/GH-F1-14-synthetic-snapshot-native-read.md](plans/GH-F1-14-synthetic-snapshot-native-read.md) | Piloto de snapshot sintético por cópia de inode novo e canário SRT de leitura nativa; ainda sem agentes |
| [plans/GH-F1-15-synthetic-snapshot-race.md](plans/GH-F1-15-synthetic-snapshot-race.md) | Canário de concorrência com seis interleavings fictícios para detectar mutações no snapshot; STRONG bloqueado |
| [plans/GH-F1-16-synthetic-aba-root-fd-diagnostic.md](plans/GH-F1-16-synthetic-aba-root-fd-diagnostic.md) | Diagnóstico sintético de ABA não detectado e troca de caminho de root_fd; STRONG indisponível |
| [plans/GH-F1-7-orquestracao-hierarquica.md](plans/GH-F1-7-orquestracao-hierarquica.md) | Estudo da futura GH-F1.7 (orquestrador e 12 especialistas), não aprovada |
| [../agents/README.md](../agents/README.md) | Definições documentais dos agentes `planner`, `implementer` e `auditor` (GH-F1.2) |
| [adr/ADR-009-contratos-de-agente-skill-tarefa.md](adr/ADR-009-contratos-de-agente-skill-tarefa.md) | Decisão sobre os contratos |
| [plans/GH-F1-arquitetura-inicial-agentes.md](plans/GH-F1-arquitetura-inicial-agentes.md) | Proposta de arquitetura dos 3 agentes da GH-F1 (planejamento) |
| [plans/sandbox-gh-f1.md](plans/sandbox-gh-f1.md) | Autorização original para sandbox em `~/Projetos/` (não criado nesse caminho); ambiente histórico separado em `/home/agent-pilot/` |
| [plans/GH-F1-5-preflight-reconciliation.md](plans/GH-F1-5-preflight-reconciliation.md) | Verificação estática de agentes read-only; execução não autorizada |
| [pilotos/GH-F1-5-reconciliacao-2026-10-24.md](pilotos/GH-F1-5-reconciliacao-2026-10-24.md) | Diagnóstico das rodadas anteriores e gates de isolamento; PR #9 preservado em Draft |
| [../policies/inventario-ferramentas-integracoes.md](../policies/inventario-ferramentas-integracoes.md) | Inventário de ferramentas e integrações |
| [../policies/matriz-riscos-permissoes-aprovacoes.md](../policies/matriz-riscos-permissoes-aprovacoes.md) | Matriz de riscos, permissões e aprovações |
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
