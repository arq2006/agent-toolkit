# ADR-007 — Arquitetura de diretórios

**Status:** aceita (F0.2, 22/10/2026)

## Contexto
O PDF (seção 13) propõe `agents/`, `skills/`, `policies/`, `workflows/`, `connectors/`, `adapters/`, `experiments/`; o README sugeria `.claude/agents/`, `.claude/skills/`, `src/`, `integrations/`. As duas versões conflitavam, e o objetivo exige compatibilidade com Claude Code sem prender o toolkit a ele (Codex, Hermes e outros).

## Decisão
1. Fonte de verdade neutra na raiz: `policies/`, `agents/`, `skills/`, `workflows/`, `experiments/`, `tests/`, `examples/`.
2. `integrations/` agrupa o que toca ferramentas e provedores: `claude-code/`, `codex/`, `hermes/`, `mcp/`, `adapters/template/`.
3. `.claude/` é camada de materialização para Claude Code; o mecanismo (cópia, symlink, plugin) é decidido na GH-F1 conferindo a documentação oficial.
4. Adaptadores específicos de projetos vivem nos próprios projetos; aqui só o modelo.
5. Diretórios só são criados quando houver conteúdo real, na fase indicada em [ARQUITETURA.md](../ARQUITETURA.md).

## Alternativas
- Fonte direta em `.claude/`: mais simples para Claude Code, mas acopla o toolkit a uma ferramenta. Rejeitada; reavaliar na GH-F1 se a materialização se mostrar custosa.
- Seguir só a árvore do PDF: perde o ponto de entrada nativo do Claude Code. Rejeitada.

## Consequências
- Risco de duplicação entre fonte e `.claude/`; mitigado por sincronização com dry-run e teste de contrato.
- Questão em aberto para a GH-F1: confirmar o suporte atual do Claude Code a symlinks e plugins.
