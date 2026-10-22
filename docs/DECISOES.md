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

## Registro de auditoria independente
Nas F0.1 e F0.2 **não houve auditoria independente do Codex** (indisponível no ambiente de nuvem). Houve apenas revisão própria do implementador e verificações automáticas (checksums, links, consistência) mais a revisão humana do PR.

## Pendências
- Linguagem e runtime preferidos para ferramentas próprias.
- Formato do contrato de tarefas e mecanismo de armazenamento do catálogo.
- Política de custos e seleção de modelos.
- ~~Importação e validação dos dois documentos completos de origem.~~ Concluída na F0.1 (PRs #1 e #2, integrados na main), com SHA-256 em [CHECKSUMS.sha256](CHECKSUMS.sha256).
- ~~Reconciliação de estrutura de pastas, lacuna de compliance do PDF F3 e numeração única de fases.~~ Tratadas na F0.2 (ADR-006, ADR-007, ADR-008); PR #3 integrado na main (62a99c0).
- **Auditoria independente (Codex) das F0.1 e F0.2 continua pendente**; não foi realizada. Executar na máquina do Arthur, com autorização.
- ~~Inventário de ferramentas e matriz de risco/aprovação (GH-F0).~~ Criados em [policies/](../policies/) (aguardam revisão humana do PR).
- GH-F1: formato dos contratos de agente, skill e tarefa; mecanismo de materialização em `.claude/`.
- GH-F2: formato final dos artefatos de compliance e skill `legal-web-check`.
- Estratégia de publicação do toolkit em outros repositórios sem copiar credenciais.
