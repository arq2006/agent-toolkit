# GH-F1.12 — Catálogo de 12 domínios e delegação hierárquica offline

**Estado: protótipo consultivo / Draft PR, sem materializar orquestrador ou agentes especializados.** Não implementa nem aprova automaticamente a GH-F1.7 futura. Reutiliza somente a política GH-F1.10 e o planejador de lote GH-F1.11, ambos já integrados.

## Objetivo

Modelar **delegação responsável e sem escalonamento de privilégios** antes da interface visual e antes de carregar especialistas no Claude Code. Nenhum código deste PR invoca Agent Teams, Claude, Codex, hooks, MCP, Bash, modelo local/nuvem, rede, repositórios externos ou leitura/gravação de arquivos reais.

Arquivos novos:
- `scripts/agent_delegation_preview.py`: `preview_delegations(policy, assignments, delegations, root_task)`, `describe_catalogue()` e CLI somente `--synthetic-only [--json]`.
- `tests/test_agent_delegation_preview.py`: **38 regressões sintéticas**; sem execução real.
- Este plano e referência no índice da documentação.

## Hierarquia proposta (somente descrição)

```text
Humano (aprovador externo) + ChatGPT (planejamento)
  └─ Claude principal                 [identificador simbólico]
      └─ orchestrator                 [NÃO instalado / NÃO executável]
          ├─ especialista em QA       [catálogo, NÃO instalado]
          ├─ especialista segurança   [catálogo, NÃO instalado]
          └─ demais domínios          [catálogo, NÃO instalado]
Codex: revisão externa independente, fora da hierarquia.
```

A função aceita apenas arestas simbólicas `orchestrator -> especialista`; todas referenciam o mesmo `root_task` fictício e profundidade calculada de **2 abaixo do Claude principal**. Descrições de subagentes, ferramentas, worktrees reais e profundidade real de runtime ainda não existem. Não é declaração de que alguma ferramenta já oferece a proteção necessária.

## Catálogo consultivo (12 domínios)

| Domínio | Papéis-base *propostos* |
|---|---|
| frontend | planner, implementer, auditor |
| backend | planner, implementer, auditor |
| apis | planner, implementer, auditor |
| ui-ux | planner, implementer, auditor |
| documentation | planner, implementer, auditor |
| security | planner, auditor |
| qa | planner, auditor |
| architecture | planner, auditor |
| database | planner, auditor |
| devops | planner, auditor |
| performance | planner, auditor |
| management | planner, auditor |

Papéis-base de `planner` e `auditor` não escrevem. `implementer` em domínios listados significa **apenas candidato a plano**, não autorização de ferramenta ou escrita. Os sete domínios restantes ficam conservadoramente em leitura/revisão até documentação específica, procedimento de segurança e autorização adicional. A análise Claude na área `auditor` **não substitui** auditoria independente Codex.

## Contrato de entrada

- `policy` e `assignments`: exatamente os contratos das GH-F1.10/GH-F1.11; o resultado de `batch.plan_batch` é **recalculado internamente**, nunca recebido como decisão confiável do solicitante.
- `root_task`: identificador simbólico válido e distinto de todas as tarefas-filhas.
- `delegations`: **uma por tarefa** do lote, com objeto de campos exatos `task_id`, `parent_task`, `delegated_by`, `delegated_to`, `base_role`, `domain`.
- `parent_task` deve ser `root_task`; `delegated_by` deve ser literalmente `orchestrator`; `delegated_to` precisa ser o mesmo `agent_id` simbólico da atribuição, exceto identificadores reservados `claude-main`, `orchestrator`, `human`, `codex`.
- `base_role` e `domain` precisam coincidir **exatamente** com o papel e especialidade da tarefa admitida. Ausência, duplicação, referências desconhecidas, arestas extras, campos inventados ou nesting adicional são recusados sem execução.

A falta de correspondência do grafo causa `PolicyDenied`. Papéis existentes mas não permitidos no domínio retornam `BLOCKED` e `DOMAIN_ROLE_NOT_PERMITTED`. Se GH-F1.11 já bloqueou a tarefa, ela continua bloqueada. Um `CLOUD_OWNER_REVIEW_REQUIRED` é apenas pedido de aprovação humana: não gera token, reserva de orçamento nem transferência de dados. `general` não é um dos 12 especialistas, mesmo sendo categoria admitida em GH-F1.10.

## Limites de segurança

Todas as flags continuam **sempre falsas**:

- `agent_execution_authorized`, `file_operations_authorized`, `cloud_call_authorized`, `data_transfer_authorized`
- `orchestrator_installed`, `specialist_agents_installed`, `human_approvals_verified`, `independent_codex_audit_verified`
- `filesystem_isolation_verified`, `real_reservations_verified`, `git_worktrees_verified`, `budget_ledger_verified`
- em cada delegação: `task_approved`, `owner_approval_inherited`, `action_authorizations_inherited`, `delegation_activated`, `tools_constrained_by_runtime`, `independent_codex_audit_verified`.

**Aprovações não são herdadas.** Uma tarefa aprovada não concede permissão para outra; ninguém abaixo do humano pode autorizar push, PR, merge, rede, dados externos ou acesso a credenciais. O motor somente revalida entradas textuais **fictícias**, não confere permissões Linux, isolamento, symlinks, hardlinks, mounts, TOCTOU, Git real, RBAC ou gasto real.

Continua valendo `STRONG=UNAVAILABLE`, `agent_execution_authorized=false`, `file_operations_authorized=false`. PR #9, `.claude/`, `agents/`, `integrations/isolation/`, matrizes de risco, contratos-base e outros repositórios não são alterados.

## Validação no Arch (Fish)

Na branch limpa GH-F1.12 baseada na `main` atual:

```fish
python3 -I -m unittest discover -s tests -p 'test_agent_delegation_preview.py' -v
python3 scripts/agent_delegation_preview.py --synthetic-only --json
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

**Contagens esperadas, não ainda comprovadas no Arch para esta branch:** 38 testes novos, **188 gerais** (150 integrados + 38), **189 de isolamento**. Antes de eventual merge: testes completos no Arch, auditoria independente Codex read-only sobre HEAD fixo, reparação de achados, revisão do escopo e autorização humana **específica para o PR**.

## Etapas futuras

1. Completar isolamento de filesystem/processo, hardlinks, bind mounts e ferramentas nativas; não confundir contratos com segurança real.
2. Obter autorização própria para GH-F1.7 antes de materializar o `orchestrator` e os 12 agentes; definir ferramentas, matriz de riscos e pilotos read-only.
3. Integrar reservas reais, contabilidade do orçamento e fluxo humano por ação, sem nuvem automática.
4. Somente depois implementar interface/mini-app com Claude e skills.
