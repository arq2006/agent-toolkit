# Registro de decisões arquiteturais (ADR simplificado)

## ADR-001 — Toolkit independente
**Status:** adotada. Código e política reutilizáveis não dependem do Solenne ou de qualquer produto individual. Personalizações ficam em adaptadores opcionais.

## ADR-002 — Repositório público e segredos
**Status:** adotada. Somente definições, exemplos sanitizados, testes e documentação públicos. Credenciais, dados pessoais, memórias privadas do agente pessoal e logs sensíveis permanecem fora do Git.

## ADR-003 — Claude implementa; Codex audita
**Status:** adotada como fluxo desejado. Claude Code realiza implementações em escopo autorizado. Codex revisa de forma independente e read-only por padrão. Humano aprova integração.

## ADR-004 — Concorrência com ownership
**Status:** adotada. Agentes paralelos não compartilham propriedade de arquivos durante escrita. Worktrees separadas e coordenação pelo líder são mandatórias quando houver mudanças simultâneas.

## ADR-005 — Ativação progressiva
**Status:** adotada. Iniciar com agentes de leitura, depois escrita controlada, depois MCP e integrações. Hermes com controle do computador, automações de contas e WhatsApp exigem aprovação específica.

## ADR-006 — Correspondência de fases PDF × GitHub
**Status:** aceita (F0.2). GH-F0 a GH-F6 são a referência operacional; o PDF (PDF-F0 a PDF-F7) é preservado. Ver [adr/ADR-006-correspondencia-de-fases.md](adr/ADR-006-correspondencia-de-fases.md). Nome canônico `agent-toolkit`; repositório público.

## ADR-007 — Arquitetura de diretórios
**Status:** aceita (F0.2). Fonte neutra na raiz, `integrations/` para ferramentas e provedores, `.claude/` como materialização. Ver [adr/ADR-007-arquitetura-de-diretorios.md](adr/ADR-007-arquitetura-de-diretorios.md) e [ARQUITETURA.md](ARQUITETURA.md).

## ADR-008 — Compliance jurídico separado do técnico
**Status:** aceita (F0.2). 17 itens, mapa de dados e relatório por projeto em [compliance/](compliance/README.md). Ver [adr/ADR-008-compliance-juridico-separado-do-tecnico.md](adr/ADR-008-compliance-juridico-separado-do-tecnico.md).

## Marco: GH-F0.2 concluída (22/10/2026)
PR #3 integrado na main com autorização explícita de Arthur (commit de merge 62a99c0). Em seguida: inventário de ferramentas e matriz de riscos/permissões/aprovações em `policies/` e plano da arquitetura GH-F1 em [plans/GH-F1-arquitetura-inicial-agentes.md](plans/GH-F1-arquitetura-inicial-agentes.md) (proposta, sem implementação).

## ADR-009 — Contratos de agente, skill e tarefa
**Status:** aceita na integração do PR #5 (GH-F1.1, commit de merge `e32a118`). Ver [adr/ADR-009-contratos-de-agente-skill-tarefa.md](adr/ADR-009-contratos-de-agente-skill-tarefa.md) e [contratos/](contratos/README.md).

## Marco: GH-F0 concluída (22/10/2026)
PRs #1, #2, #3 e #4 integrados na main (o #4 em `504156e`, autorização explícita de Arthur específica para esse PR). Documentos originais intactos (checksums OK). Auditoria independente do Codex continua **pendente**.

## Marco: GH-F1.1 concluída (22/10/2026)
PR #5 integrado na main (`e32a118`) com autorização explícita de Arthur específica para esse PR (commit aprovado `ed522ed`). Em seguida: GH-F1.2, definições documentais dos três agentes em [`agents/`](../agents/README.md), em PR separado (rascunho). Registrado para a GH-F1.3: o alvo da autorização `open_pr` deve usar repositório e branches head/base antes da criação do PR, sem exigir número inexistente. Auditoria independente do Codex continua **pendente**.

## ADR-010 — Materialização em `.claude/`
**Status:** proposta (GH-F1.3). Ver [adr/ADR-010-materializacao-em-claude-code.md](adr/ADR-010-materializacao-em-claude-code.md) e a [pesquisa](pesquisas/claude-code-materializacao-2026-10-22.md).

## Marco: GH-F1.2 concluída (22/10/2026)
PR #6 integrado na main (`f60e695`, HEAD aprovado `053d289`) com autorização explícita de Arthur específica para esse PR. GH-F1.3 em revisão: pesquisa da documentação do Claude Code, ADR-010 (proposta), correção do alvo da autorização `open_pr` (contrato de tarefa 0.1.1), critério de estado Git do `planner` (v0.1.1: comparar estado inicial e final, sem exigir árvore limpa) e registro da GH-F1.7 como proposta futura (orquestração hierárquica e 12 especialistas; [estudo](plans/GH-F1-7-orquestracao-hierarquica.md)), **não aprovada**. Auditoria independente do Codex continua **pendente**.

## Decisões da GH-F1 (22/10/2026, Arthur)
Divisão em seis PRs aprovada; agentes `planner`, `implementer`, `auditor`; Sonnet com esforço médio por padrão; Codex como auditor independente quando disponível, planejado após a GH-F1.4 e antes da primeira escrita do piloto, sem ser exigido antes da GH-F1.1. **Um auditor Claude em contexto separado não substitui a auditoria independente do Codex.** Merge: autorização humana obrigatória e específica por PR, com execução delegável ao Claude; proteção de branch fica separada e bloqueada sem autorização especial. Sandbox local condicionado, **não criado**: [plans/sandbox-gh-f1.md](plans/sandbox-gh-f1.md).

## ADR-011 — Isolamento portátil do processo
**Status:** proposta (GH-F1.8, identificador provisório; 24/10/2026). Ver [adr/ADR-011-isolamento-do-processo.md](adr/ADR-011-isolamento-do-processo.md). Direção aprovada por Arthur: Python 3.11+ (biblioteca padrão) e TOML em `integrations/isolation/`; STRONG só com validação efetiva do `doctor` (leitura/escrita, subprocessos, caminhos indiretos, hardlinks, fail-closed); coordenador autenticado fora do sandbox não é isolamento integral. Spike manual (Arch, 24/10) comprovou bubblewrap e srt sem sudo; hardlinks preexistentes são limitação confirmada. **Nada implementado e nenhum ambiente é STRONG.** GH-F1.5 preservada; GH-F1.6 bloqueada.

**PR3 (GH-F1.8, 24/10/2026):** launcher SRT e `toolkit_doctor` em `integrations/isolation/`, com srt fixado em 0.0.81, rede só em deny e canários apenas em fixture sintético. STRONG permanece indisponível e operações com arquivos, BLOCKED; o resultado do doctor não autoriza execução de agentes. Detalhes e limites em `integrations/isolation/README.md`.

## Registro de auditoria independente
Nas F0.1 e F0.2 **não houve auditoria independente do Codex** (indisponível no ambiente de nuvem). Houve apenas revisão própria do implementador e verificações automáticas (checksums, links, consistência) mais a revisão humana do PR.

## Pendências
- Linguagem e runtime preferidos para ferramentas próprias.
- Formato do contrato de tarefas e mecanismo de armazenamento do catálogo.
- Política de custos e seleção de modelos.
- ~~Importação e validação dos dois documentos completos de origem.~~ Concluída na F0.1 (PRs #1 e #2, integrados na main), com SHA-256 em [CHECKSUMS.sha256](CHECKSUMS.sha256).
- ~~Reconciliação de estrutura de pastas, lacuna de compliance do PDF F3 e numeração única de fases.~~ Tratadas na F0.2 (ADR-006, ADR-007, ADR-008); PR #3 integrado na main (62a99c0).
- **Auditoria independente (Codex) das F0.1 e F0.2 continua pendente**; não foi realizada. Executar na máquina do Arthur, com autorização.
- ~~Inventário de ferramentas e matriz de risco/aprovação (GH-F0).~~ Criados em [policies/](../policies/) (PR #4 integrado).
- ~~GH-F1: formato dos contratos de agente, skill e tarefa.~~ Integrados na GH-F1.1 ([contratos/](contratos/README.md)).
- ~~GH-F1.3: alvo de `open_pr` e mecanismo de materialização.~~ Resolvidos na GH-F1.3 ([ADR-010](adr/ADR-010-materializacao-em-claude-code.md), PR #7 integrado).
- GH-F1.4 (em revisão): `implementer` em `.claude/agents/` não gravado (aguarda autorização); `@AGENTS.md` no `CLAUDE.md` aguarda decisão; esquema formal e formato do arquivo de tarefa seguem em aberto. Ver [materializacao-claude-code.md](materializacao-claude-code.md).
- GH-F2: formato final dos artefatos de compliance e skill `legal-web-check`.
- Estratégia de publicação do toolkit em outros repositórios sem copiar credenciais.
