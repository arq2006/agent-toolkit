# Roteiro de início para Claude Code

Este arquivo orienta qualquer sessão de trabalho. Não tente implementar o ecossistema em um único PR.

## Estado atual (atualizado na F0.2)
- **GH-F0 / F0.1 concluída:** PDF e roadmap de segurança geral importados sem alterações (PRs #1 e #2), com SHA-256 em [CHECKSUMS.sha256](CHECKSUMS.sha256).
- **GH-F0 / F0.2 (consolidação documental) concluída** (PR #3, 62a99c0): numeração de fases, arquitetura de diretórios ([ARQUITETURA.md](ARQUITETURA.md)) e estrutura de compliance ([compliance/](compliance/README.md)) documentadas. Decisões em [DECISOES.md](DECISOES.md).
- **GH-F0 concluída:** inventário e matriz de riscos/permissões/aprovações em [../policies/](../policies/) (PR #4).
- **GH-F1.1 concluída:** contratos de agente, skill e tarefa em [contratos/](contratos/README.md) (PR #5).
- **GH-F1.2 concluída:** definições documentais de `planner`, `implementer` e `auditor` em [../agents/](../agents/README.md) (PR #6).
- **GH-F1.3 (concluída, PR #7):** [pesquisa](pesquisas/claude-code-materializacao-2026-10-22.md), [ADR-010](adr/ADR-010-materializacao-em-claude-code.md) (proposta), correções de contrato e estudo da futura [GH-F1.7](plans/GH-F1-7-orquestracao-hierarquica.md); GH-F1.4 em diante só com autorização por etapa.
- **Próximo:** GH-F1 (agentes Claude Code), **somente após autorização humana específica**; proposta em [plans/GH-F1-arquitetura-inicial-agentes.md](plans/GH-F1-arquitetura-inicial-agentes.md).
- Auditoria independente do Codex: **não realizada** na F0.1 nem na F0.2 (indisponível no ambiente de nuvem); só houve revisão própria e leitura humana; a auditoria continua **pendente**. Registrar o mesmo em fases futuras se continuar assim.

## Restrições que continuam valendo
Não instalar Hermes, FreeLLMAPI, ElevenLabs ou servidores MCP, não ativar Agent Teams, hooks ativos nem automações, e não criar agentes ou scripts executáveis sem uma tarefa autorizada.

## Instruções para cada sessão
1. Leia README.md, CLAUDE.md, AGENTS.md, docs/ROADMAP_IMPLEMENTACAO.md, docs/DECISOES.md e docs/FONTES_E_IMPORTACAO.md.
2. Confirme `git status`, branch e HEAD; preserve todo trabalho que não seja seu.
3. Verifique a integridade: `cd docs && sha256sum -c CHECKSUMS.sha256`.
4. Faça o inventário da etapa em modo read-only e apresente o plano (escopo, arquivos, testes, riscos). Aguarde aprovação.
5. Crie branch própria a partir da `main` atualizada, faça commits pequenos com stage explícito e abra PR em rascunho. Nunca faça merge.

## Para a GH-F1 (quando autorizada)
Propor apenas 3 agentes iniciais (planejador, implementador, auditor/revisor) e suas permissões, seguindo o layout de [ARQUITETURA.md](ARQUITETURA.md) e verificando a documentação oficial atual do Claude Code antes de definir a materialização em `.claude/`.

## Entrega esperada de cada tarefa
Branch e HEAD, arquivos alterados, decisões, testes/validações, riscos, pendências, comandos executados e URL do PR.
