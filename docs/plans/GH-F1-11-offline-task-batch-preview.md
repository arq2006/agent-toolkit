# GH-F1.11 — Pré-coordenação offline de tarefas e arquivos

**Estado: proposta funcional inativa em Draft PR. Não é a GH-F1.7 e não aprova criar o `orchestrator` ou os 12 especialistas.**

## Objetivo

Antes de criar telas ou executar agentes, comprovar com dados fictícios as decisões de coordenação em lote que serão necessárias para trabalho paralelo: dono exclusivo dos arquivos, contexto simbólico de branch/worktree, papéis com permissões distintas, política local-first e bloqueio de nuvem. A implementação reutiliza a política da **GH-F1.10** já integrada e **não a altera**.

## Escopo deste PR

- `scripts/agent_batch_plan.py`: biblioteca pura `plan_batch(policy, assignments)`; CLI somente `--synthetic-only [--json]`. **Sem argumentos de workspace, arquivo real, agente ou token.**
- `tests/test_agent_batch_plan.py`: **33 testes** sintéticos e negativos, incluindo conflitos com três tarefas, tags duplicadas, agentes repetidos, grants inválidos e orçamento de nuvem.
- Este plano e a entrada em `docs/README.md`.

### Contrato sintético do lote

`policy`: exatamente o contrato `version=2` da GH-F1.10, incluindo `editable`, `read_only`, `protected` e limites de custo **ilustrativos**.

`assignments`: lista de 1 a 16 objetos com **chaves exatas**:

- `task`: requisição integral do `agent_task_policy.evaluate` (incluindo `task_id`, `role`, `specialty`, `action`, `provider`, `paths`, `complexity`, disponibilidade local e estimativas/custos).
- `agent_id`: identificador simbólico, sem relação com um agente realmente instalado. Duplicações no mesmo lote são recusadas.
- `branch_tag`, `worktree_tag`: identificadores simbólicos únicos e obrigatórios **para declarações de escrita**; ambos são `null` em tarefas de leitura. Não são caminhos nem refs Git verificadas.

A definição de `specialty` (frontend/backend/QA/segurança etc.) é apenas **taxonomia**, não cria, materializa ou convoca especialistas. Os domínios `database`, `devops`, `performance` e `management` são **somente leitura/proposta** nesta etapa; requisições de escrita são bloqueadas com `SPECIALTY_WRITE_REQUIRES_SEPARATE_PROCEDURE`.

### Resultados consultivos

- `LOCAL_PLAN_ONLY`: escopo textual e contexto simbólico parecem compatíveis; **não inicia trabalho**.
- `CLOUD_OWNER_REVIEW_REQUIRED`: somente *pedido* de revisão humana e autorização separada de transferência de dados, sem uso da nuvem.
- `BLOCKED`: o pedido não satisfaz o contrato ou há ambiguidade/colisão. Entradas estruturalmente inválidas causam `PolicyDenied` (fail-closed).

Conflitos são verificados para **todos** os pares de candidatas, sem depender da ordem; leitura/leitura sobre o mesmo arquivo é compatível. Qualquer par com escritor e escopos textualmente sobrepostos é bloqueado nos dois lados. Duas escritas não podem usar a mesma tag de branch ou de worktree. Nenhuma execução acontece, mesmo quando não há conflitos. Escopos dentro de uma única tarefa com relação de ancestralidade também são recusados como ambíguos. Se várias tarefas no mesmo lote solicitam nuvem, o lote não afirma reserva consolidada de orçamento: as propostas de nuvem são bloqueadas com `CLOUD_BATCH_BUDGET_NOT_VERIFIED`. Mesmo uma única tarefa de nuvem requer aprovação humana e de envio de dados.

### Invariantes imutáveis

Sempre `false`:
- `agent_execution_authorized`
- `file_operations_authorized`
- `cloud_call_authorized`
- `data_transfer_authorized`
- `filesystem_isolation_verified`
- `real_reservations_verified`
- `git_worktrees_verified`
- `budget_ledger_verified`
- `human_approvals_verified`

**Não interpretar** `LOCAL_PLAN_ONLY` ou um `branch_tag` como autorização, reserva, licença de acessar disco ou evidência de isolamento STRONG. A implementação não examina paths reais, symlinks/hardlinks, bind mounts, TOCTOU, permissões efetivas de Read/Edit/Bash, status Git, assinaturas de aprovações, provedor/VRAM ou medição de tokens. Opera apenas com objetos fictícios em memória. `STRONG=UNAVAILABLE` e `agent_execution_authorized=false` continuam valendo no toolkit.

## Relação com o planejamento existente

- Não altera o contrato de tarefa 0.1.1; apenas prova regras que poderão ser integradas a instâncias de tarefas aprovadas **no futuro**.
- **GH-F1.7**, sua biblioteca de especialistas, Agent Teams, hooks, MCP e execução de agentes continuam fora do escopo e dependem de aprovação própria.
- O PR #9 continua intocado. Solenne, FIINA, Velaris, sistema operacional e diretórios externos não são utilizados.
- O futuro gerenciador de pastas e interface visual só deverão ser conectados após validação real do filesystem, proteção de ferramentas, ledger confiável e autorização humana por ação.
- **Worktrees reais, instalação de agentes, API Ollama/LM Studio, nuvem e merges não são realizados por este PR.**

## Testes no Arch (Fish)

```fish
python3 -I -m unittest discover -s tests -p 'test_agent_batch_plan.py' -v
python3 scripts/agent_batch_plan.py --synthetic-only --json
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

Esperado no código proposto: **33 testes novos**, **150 gerais** (117 previamente integrados + 33), **189 de isolamento** (suíte existente), sem alterações locais; ainda **não comprovado no Arch**. Executar apenas no repositório `agent-toolkit` com branch e HEAD corretos. Não executar em projetos reais.

Gates antes de eventual merge: testes completos no Arch, revisão Codex read-only em HEAD fixo, correções de achados, revisão humana e **autorização específica para este PR**.
