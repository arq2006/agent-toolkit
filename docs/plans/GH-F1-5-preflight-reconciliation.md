# GH-F1.5 — Pré-validação estática e reconciliação do PR #9

**Estado: pré-validação estática concluída nesta etapa; a execução real anterior foi analisada documentalmente em 24/10.** Este PR de pré-validação não executou agentes nem criou sandbox, conta, hook, skill, MCP, worktree ou configuração. A análise de evidências históricas está em [GH-F1.5 — Reconciliação de evidências e arquitetura](../pilotos/GH-F1-5-reconciliacao-2026-10-24.md).

**Resultado histórico posterior ao registro inicial abaixo:** no dispositivo do operador, `agent-pilot` e `/home/agent-pilot/agent-toolkit-sandbox` **já existem**. Duas rodadas anteriores apresentaram snapshots Git idênticos, hashes conferidos e inventário efetivo `Read/Grep/Glob`; outra rodada permanece incompleta. Nenhuma das rodadas realizou chamada `Read` ao alvo externo no probe; **isolamento de leitura externa não comprovado**. Não repetir instruções de criação de sandbox por causa deste registro. Os números relativos ao PR #9 abaixo são um **snapshot de consulta anterior**; ver a reconciliação para os números mais recentes.

## Situação real verificada no GitHub (24/10/2026)

- [PR #8](https://github.com/arq2006/agent-toolkit/pull/8) — GH-F1.4 materializou `planner` e `auditor` em `.claude/agents/`. Ambos têm, nas definições versionadas, somente `Read, Grep, Glob`; `implementer` permanece não materializado.
- [PR #9](https://github.com/arq2006/agent-toolkit/pull/9) — GH-F1.5 está **aberto em Draft** e não integrado. Na comparação observada com a main em 24/10, a branch tinha **13 commits à frente / 32 atrás** da main. O PR descreve piloto **parcialmente executado**, sem aceite integral, e contém guias, fixture e protocolo que ainda não estão na main.
- O conteúdo atual do PR #9 relata **achados de uma auditoria Codex sobre aquele PR** e correções documentais ainda sem reteste real. Isso não é evidência de que a auditoria local exigida para o futuro piloto de **escrita GH-F1.6** foi concluída. Registrar cada auditoria por alvo, versão e evidência; não colapsar tudo em "Codex não rodou" nem assumir que o PR #9 está validado.
- [ADR-011](../adr/ADR-011-isolamento-do-processo.md) descreve evolução para SRT/bubblewrap, limitação de hardlinks e classificação STRONG ainda **não demonstrada**. O PR #9, mais antigo, prescreve conta Linux dedicada e caminhos `/home/agent-pilot/`; não executar essa prescrição como padrão enquanto a decisão de arquitetura não estiver reconciliada com ADR-011 e as autorizações de caminho/conta.
- O [SRT Doctor](../../integrations/isolation/README.md) testa canários **sintéticos**. Mesmo um resultado de sucesso não autoriza agentes, e os agentes nativos `Read/Edit` não herdam o isolamento do `pathguard`. Não usar PR #12 como prova de STRONG.

## Entrega pequena desta branch (distinta do PR #9)

`scripts/preflight_readonly_agents.py` examina **somente arquivos versionados da cópia local deste repositório**:

1. Exige precisamente `.claude/agents/planner.md` e `auditor.md`, sem um `implementer.md` ou agente inesperado.
2. Rejeita links simbólicos na cadeia desses caminhos e da fonte neutra `agents/{planner,auditor}/AGENT.md`.
3. Exige frontmatter estrito, com `tools: Read, Grep, Glob` e bloqueios declarados de `Bash, Write, Edit, NotebookEdit, Agent, WebFetch, WebSearch`; recusa campos extras de configuração que ampliem poderes.
4. Confere declarativamente modo read-only, proibição de escrita e níveis A0 na fonte neutra. **Não** faz parse YAML completo nem avalia todos os campos ou o comportamento real das ferramentas.
5. Devolve `CONFIG_OK` ou `CONFIG_INVALID`. Um resultado `CONFIG_OK` **NÃO** significa `READY` para piloto: os campos `agent_execution_authorized`, `tool_access_effectively_verified`, `filesystem_isolation_verified`, `network_isolation_verified` e `sandbox_fixture_verified` são explicitamente `false`; `pilot_acceptance` permanece `PENDING`.

O validador usa só a biblioteca padrão Python, lê arquivos locais de configuração e não invoca Claude, Git, subprocessos, network sockets ou `toolkit doctor`. **A própria execução do validador não cria evidência de proteção do processo**: prompts, ferramentas declaradas e caminho de trabalho não restringem por si só leitura fora da pasta permitida.

## Antes do piloto real — gates independentes

1. **Resolver o PR #9:** conferir o diff contra a main atual e preservar evidências históricas. Reconciliar os passos de conta dedicada, caminhos aprovados, possíveis sandboxes/contas já existentes e as novas limitações da ADR-011. Não fazer merge, rebase destrutivo ou sobrescrever a branch automaticamente. Se PR #9 permanecer no caminho antigo, mantê-lo em Draft até revisão e autorização.
2. **Checar o dispositivo:** confirmar versão instalada do Claude Code, SRT/bwrap se usados, estado do repositório e se o caminho autorizado do sandbox existe ou não. Nunca presumir que um diretório está vazio ou descartável. Não executar instruções que criem conta, alterem permissões ou instalem pacotes sem autorização por operação.
3. **Comprovar fronteira:** teste com controles positivos e negativos para a leitura *real* via `Read/Grep/Glob` sob o contexto de autenticação escolhido; testar escrita negada, subprocessos e rede quando relevantes. Hardlinks/symlinks, montagens e processo autenticado fora da fronteira são pendências específicas. Nenhuma permissão efetiva pode ser inferida só da presença de `disallowedTools`.
4. **Somente depois** de decidir a arquitetura e obter autorização humana de execução: usar fixture sintética e os dois agentes read-only; snapshots antes/depois, hashes e logs privados, custo/tokens, evidência real de não alteração. Não rodar `implementer`, não usar projetos reais e não fazer push remoto.
5. Reavaliar o status da GH-F1.5 com evidências reais e decisão humana. A GH-F1.6 (escrita) continua bloqueada. Auditoria independente do Codex referente à GH-F1.6 ainda depende de evidência própria.

## Validação desta etapa (Arch, Fish)

Após entrar **na branch deste novo PR** e confirmar `git status --short` sem alterações:

```fish
python3 scripts/preflight_readonly_agents.py
python3 -m unittest discover -s tests -p 'test_readonly_agents_preflight.py' -v
```

Resultado esperado: `CONFIG_OK`, dois agentes, todos os campos de execução e isolamento efetivo `false`, mais 20 testes de regressão aprovados.

**O PR #9 não é modificado por esta etapa.** Os arquivos de referência e segurança originais, os agentes materializados e `integrations/isolation/` também permanecem inalterados. A nova branch só acrescenta este procedimento de revisão, script e testes. O merge exige autorização humana específica.
