# Agent Toolkit

Ecossistema reutilizável de agentes de IA, skills, ferramentas e fluxos de trabalho para diferentes projetos.

> Estado atual: **fundação documental em preparação**. Nenhum agente autônomo, integração externa ou rotina de execução está habilitado por este repositório.

## Objetivos

- Coordenar Claude Code, Codex e outros agentes com responsabilidade por tarefa, revisão independente e integração manual.
- Criar skills e ferramentas próprias, com interfaces documentadas, testes e permissões mínimas.
- Manter segurança e conformidade como controles reutilizáveis, adaptados a cada produto.
- Investigar Hermes Agent, MCP, voz e multimodalidade em ambientes isolados.
- Experimentar roteamento de modelos e otimização de custo de forma mensurável.
- Evitar dependência de qualquer projeto existente, incluindo Solenne, FIINA ou Velaris.

## Começar

1. Consulte [docs/ROADMAP_IMPLEMENTACAO.md](docs/ROADMAP_IMPLEMENTACAO.md).
2. Leia [CLAUDE.md](CLAUDE.md) e [AGENTS.md](AGENTS.md).
3. Confira [docs/FONTES_E_IMPORTACAO.md](docs/FONTES_E_IMPORTACAO.md) antes de alterar os documentos de referência.
4. Use [docs/HANDOFF_CLAUDE.md](docs/HANDOFF_CLAUDE.md) para iniciar o trabalho no Claude Code.
5. Abra uma branch por entrega, com testes, auditoria e PR; **não use merge automático**.

## Organização planejada

- `docs/`: planejamento, estudos, decisões, segurança e manuais.
- `.claude/agents/`: definições de agentes específicos do toolkit.
- `.claude/skills/`: skills reutilizáveis conforme o padrão Agent Skills.
- `src/` e `tests/`: ferramentas e testes, somente quando houver uma tecnologia escolhida.
- `examples/`: exemplos com dados fictícios.
- `integrations/`: adaptadores isolados para provedores e produtos.

As pastas de código e de agentes serão implementadas pelo Claude após a fase documental, em PRs separados. Não criar arquivos artificiais apenas para preencher diretórios.

## Segurança

Repositório **público**: não publicar tokens, senhas, dados pessoais, históricos de conversas, dumps, arquivos .env reais, logs sensíveis nem cópias de configurações locais. Uma aprovação humana é necessária para integrações externas, alterações em produção, pagamentos, ações no computador e merge.

## Documentação oficial

- [Claude Code — Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code — Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code — Skills](https://code.claude.com/docs/en/skills)
- [Claude Code — Settings](https://code.claude.com/docs/en/settings)

Licenças e termos de terceiros precisam de verificação antes de qualquer redistribuição.
