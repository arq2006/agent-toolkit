# Agent Toolkit

Ecossistema reutilizável de agentes de IA, skills, ferramentas e fluxos de trabalho para diferentes projetos.

> Estado atual: **GH-F0 concluída; GH-F1.1 (contratos) em revisão**. Fases: GH-F0 a GH-F6 (ver [roadmap](docs/ROADMAP_IMPLEMENTACAO.md)). Nenhum agente autônomo, integração externa ou rotina de execução está habilitado por este repositório.

## Objetivos

- Coordenar Claude Code, Codex e outros agentes com responsabilidade por tarefa, revisão independente e integração manual.
- Criar skills e ferramentas próprias, com interfaces documentadas, testes e permissões mínimas.
- Manter segurança e conformidade como controles reutilizáveis, adaptados a cada produto.
- Investigar Hermes Agent, MCP, voz e multimodalidade em ambientes isolados.
- Experimentar roteamento de modelos e otimização de custo de forma mensurável.
- Evitar dependência de qualquer projeto existente, incluindo Solenne, FIINA ou Velaris.

## Começar

1. Consulte o [índice da documentação](docs/README.md) e o [docs/ROADMAP_IMPLEMENTACAO.md](docs/ROADMAP_IMPLEMENTACAO.md).
2. Leia [CLAUDE.md](CLAUDE.md) e [AGENTS.md](AGENTS.md).
3. Confira [docs/FONTES_E_IMPORTACAO.md](docs/FONTES_E_IMPORTACAO.md) antes de alterar os documentos de referência.
4. Use [docs/HANDOFF_CLAUDE.md](docs/HANDOFF_CLAUDE.md) para iniciar o trabalho no Claude Code.
5. Abra uma branch por entrega, com testes, auditoria e PR; **não use merge automático**.

## Organização planejada

Árvore alvo completa, mapa de reconciliação e justificativa em [docs/ARQUITETURA.md](docs/ARQUITETURA.md) (ADR-007). Resumo:

- `docs/`: planejamento, decisões, segurança, compliance e referências (existente).
- `policies/`: inventário de ferramentas e matriz de riscos, permissões e aprovações (existente).
- `agents/`, `skills/`, `workflows/`: fonte neutra de agentes, skills e fluxos (futuro).
- `integrations/`: materialização para Claude Code, Codex, Hermes, MCP e adaptador modelo (futuro).
- `.claude/`: camada de materialização para Claude Code (GH-F1).
- `experiments/`, `src/`, `tests/`, `examples/`, `scripts/`: somente quando houver conteúdo real e tecnologia escolhida.

As pastas de código e de agentes serão implementadas após a fase documental, em PRs separados. Não criar arquivos artificiais apenas para preencher diretórios.

## Segurança

Repositório **público**: não publicar tokens, senhas, dados pessoais, históricos de conversas, dumps, arquivos .env reais, logs sensíveis nem cópias de configurações locais. Uma aprovação humana é necessária para integrações externas, alterações em produção, pagamentos, ações no computador e merge.

## Documentos de referência

- [Plano do ecossistema de agentes (PDF)](docs/references/Plano_Ecossistema_Agentes_IA_2026.pdf)
- [Roadmap de segurança geral v3](docs/security/Roadmap_Seguranca_Geral_v3.md)
- [Inventário de ferramentas](policies/inventario-ferramentas-integracoes.md) e [matriz de riscos e aprovações](policies/matriz-riscos-permissoes-aprovacoes.md)
- [Contratos de agente, skill e tarefa](docs/contratos/README.md) (GH-F1.1, rascunho)
- Compliance (checklist de 17 itens, mapa de dados, relatório): [docs/compliance/](docs/compliance/README.md)
- Integridade: [docs/CHECKSUMS.sha256](docs/CHECKSUMS.sha256)

## Documentação oficial

- [Claude Code — Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code — Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code — Skills](https://code.claude.com/docs/en/skills)
- [Claude Code — Settings](https://code.claude.com/docs/en/settings)

Licenças e termos de terceiros precisam de verificação antes de qualquer redistribuição.
