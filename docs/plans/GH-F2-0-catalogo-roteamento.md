# GH-F2.0 — Catálogo consultivo e roteamento de skills

**Estado: Draft PR para revisão humana.** Primeira entrega pequena da GH-F2, sem antecipar GH-F1.7. A criação dos 12 especialistas ainda depende de GH-F1.4–F1.6 e da decisão sobre a auditoria independente do Codex. O PR GH-F1.5 permanece intocado.

## Objetivo

Mapear skills e plugins candidatos aos 12 domínios propostos, sem instalá-los ou executá-los. Entregar um seletor offline que devolve **sugestões não autorizadas**, explicitamente rotuladas, dado um agente e uma categoria de tarefa. Não há orquestração real, agentes novos, hooks, MCP, rede ou alteração de `.claude/`.

## Arquivos desta entrega

| Arquivo | Função |
|---|---|
| `skills/catalog.json` | 22 skills/plugins candidatos e quatro integrações que **não são skills** |
| `skills/README.md` | Matriz de 12 domínios, limites por especialidade e requisitos de adoção |
| `scripts/skill_router.py` | CLI consultiva, validada e determinística, só Python stdlib |
| `tests/test_skill_router.py` | Testes positivos e negativos, escalonamento de privilégios, estados desativados |
| `docs/plans/GH-F2-0-catalogo-roteamento.md` | Escopo, limitações e critérios de aceite |

## Limites e segurança

1. Nenhum pacote ou skill externo é instalado, copiado, importado ou executado. Este catálogo **não é um SKILL.md** carregável pelo Claude Code.
2. As 12 especialidades são uma **taxonomia futura**, não agentes executáveis. Os papéis existentes `planner`, `implementer`, `auditor` não são alterados.
3. `mode` é estritamente `advisory-only`. O CLI não executa comandos externos e não chama serviços, nem tem autorização para atribuir permissões; `approved_for_use` e `toolkit_installed` permanecem `false`.
4. `reported-global` é relato histórico de instalação em outro projeto, não verificação atual; skills globais preexistentes podem ser carregadas fora deste seletor.
5. Procedência, licença, scripts, hooks, rede, dependências e versão/commit de cada candidato deverão ser inspecionados antes da adoção. `superpowers` permanece desativado.
6. Sem alterações a `docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256`, `.claude/`, configurações de isolamento, outros repositórios, credenciais ou produção.
7. O SRT do PR #12 continua experimental; GH-F1.5/1.6 e auditoria Codex são pendências independentes. Nenhum isolamento STRONG ou execução real foi aprovado.

## Validação local

```bash
python3 scripts/skill_router.py validate
python3 scripts/skill_router.py suggest --agent ui-ux --tag design_system
python3 -m unittest discover -s tests -p 'test_skill_router.py' -v
```

Critérios: schema válido; máximo padrão de duas sugestões; skill `disabled` excluída; grupo de não-skills nunca roteado; tags/papéis inválidos recusados; tentativas de editar `mode`, `approved_for_use` ou `toolkit_installed` recusadas; nenhuma alteração persistente.

## Entregas futuras, cada qual sujeita a aprovação própria

- **GH-F2.1:** revisão por candidato (começar UI/UX: Impeccable, Replica Design, Anthropic Frontend Design e Vercel Web Design Guidelines; depois QA e Frontend). Fixar versão/SHA, licença, testar scripts e atualizar o inventário T-xx antes de disponibilizar `SKILL.md` + `contract.yaml`.
- **GH-F2.2 (dependente de GH-F1.7):** integração ao coordenador e subagentes reais após isolamento e permissões verificadas. Fonte neutra; adaptadores por ferramenta. Não carregar tudo no contexto.
- **GH-F3+:** OpenViking para memória segmentada, Artemis para testes Android, Unsloth para modelos locais. CodeXR segue fonte de referência visual, não skill.

## Fontes e políticas

- [Contrato da skill](../contratos/contrato-de-skill.md), [matriz A0–A3](../../policies/matriz-riscos-permissoes-aprovacoes.md) e [inventário](../../policies/inventario-ferramentas-integracoes.md).
- [GH-F1.7](GH-F1-7-orquestracao-hierarquica.md) e [roadmap](../ROADMAP_IMPLEMENTACAO.md).
- [Claude Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), [Anthropic Skills](https://github.com/anthropics/skills), [Vercel Agent Skills](https://github.com/vercel-labs/agent-skills), [Replica](https://github.com/Jakeschincariol/replica-skill).
- [OpenViking](https://github.com/volcengine/OpenViking), [Google Artemis](https://github.com/google/artemis), [Unsloth](https://github.com/unslothai/unsloth), [CodeXR](https://topmate.io/code_xr).

**Não fazer merge sem aprovação específica para este PR.**
