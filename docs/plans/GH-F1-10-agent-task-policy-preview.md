# GH-F1.10 — Política de admissão de tarefas, local-first e escopo textual

**Status:** protótipo consultivo e inativo. Sem interface, execução de agentes, API, provedor de IA, leitura de projetos ou acesso a arquivos reais.

## Objetivo e prioridade

Antes da interface visual, consolidar contratos determinísticos de admissão para os agentes, preservando as decisões do proprietário:

1. Apenas arquivos e subdiretórios **explicitamente selecionados** poderão ser candidatos a operações futuras; itens protegidos prevalecem.
2. Trabalho rotineiro usa preferencialmente **Ollama / LM Studio local** quando houver integração compatível e recursos disponíveis (integração ainda inexistente).
3. Nuvem é **negada por padrão**; escalonamento não é automático, mesmo se o modelo local falhar. Tarefas críticas/complexas/promissoras podem solicitar autorização; tarefas rotineiras precisam justificar exceção.
4. Aprovação de uso de nuvem **não implica** autorização para enviar arquivos ou dados a provedores externos. Cada autorização humana futura será escopada por tarefa, operação, conteúdo e custo.
5. Limites de custo por tarefa/dia/projeto exigem **ledger confiável**, controle de concorrência e contabilização real. Uma estimativa recebida de um agente não é garantia financeira.
6. Nunca habilitar agentes, Read/Edit nativos, execução de modelo ou ferramentas com um resultado consultivo.

## Entrega deste PR

- `scripts/agent_task_policy.py`: função pura `evaluate(policy, request)`, sem leitura de arquivos, rede, subprocesso ou modelos. Os campos de autorização da resposta são sempre `false`. CLI aceita apenas `--synthetic-only [--json]`, produzindo um exemplo inventado.
- `tests/test_agent_task_policy.py`: **28 testes** com políticas fictícias, limites por prefixo de diretório, ancestrais de diretórios protegidos, credenciais como `.env` em subpastas, papéis somente-leitura, orçamento, proibição de fallback automático para nuvem e campos de autorização forjados.
- Plano técnico e link no índice de documentação.

### Contrato consultivo

**Policy** (objeto com chaves exatas):

`version=1`, `workspace_id` (identificador simbólico, **não caminho real**), listas `editable`, `read_only`, `protected` de caminhos **relativos e puramente textuais**, e valores de demonstração em centavos de dólar: `cloud_task_cap_cents`, `cloud_day_cap_cents`, `cloud_project_cap_cents`.

**Request** (objeto com chaves exatas):

`task_id`, `role` (somente `planner`, `implementer`, `auditor`), `specialty` (domínios futuros), `action` (`read`, `write`), `paths`, `provider` (`local`, `cloud`), `complexity`, `local_available`, `estimated_cloud_cents`, `spent_today_cents`, `spent_project_cents`.

Os domínios de `specialty` são **somente taxonomia**, não instâncias de agentes. Valores financeiros do exemplo são ilustrativos para **API faturada em USD**, não são orçamentos aprovados pelo usuário nem representam cotas de assinaturas. O protótipo não mede tokens, desempenho, gastos ou disponibilidade efetiva de Ollama/LM Studio.

### Saídas

`LOCAL_PROPOSED`, `CLOUD_REVIEW_REQUIRED` ou `BLOCKED`. Essas são **propostas**, nunca capacidade de ação. Todos os resultados preservam:

- `agent_execution_authorized=false`
- `file_operations_authorized=false`
- `cloud_call_authorized=false`
- `data_transfer_authorized=false`
- `root_fd_verified=false`
- `filesystem_isolation_verified=false`
- `budget_ledger_verified=false`
- `reservation_verified=false`

O protótipo compara **somente strings relativas**. Ele não resolve caminhos de disco, symlinks, hardlinks, bind mounts, TOCTOU, permissões do kernel, worktrees, credenciais, consumo real, SRT ou autorizações humanas. A interface futura de escolha de `ArquivosEditaveis/` terá de delegar os caminhos a uma fronteira confiável independente, devidamente testada. **Não usar `textual_scope_valid` como controle de acesso.**

Selecionar um diretório-ancestral de conteúdo protegido é recusado no preflight textual. Uma resposta local que contenha código jamais constitui permissão de gravar esse código no disco.

## Ordem futura — funcional antes da UI

1. Consolidar seleção de pastas/FDs reais, proteção de caminhos e mecanismos efetivos de filesystem; reconciliar PR #9 histórico sem tocá-lo.
2. Resolver pendências de isolamento das ferramentas nativas, hardlinks, bind mounts e concorrência. **Sem isso, agentes com acesso a arquivos não são autorizados.**
3. Preparar aprovação humana por ação, auditoria e ledger de custos confiável. Não habilitar APIs pagas ou transferência de conteúdo automaticamente.
4. Criar e validar catálogo do `orchestrator` e especialistas por contrato de tarefa, com ownership, reservas exclusivas de arquivos e worktrees, inicialmente sem iniciar agentes.
5. Pilotar agentes primeiro apenas read-only em fixture descartável **nova**, depois implementação numa worktree isolada com autorização específica (GH-F1.6).
6. Integrar modelos locais Ollama/LM Studio em opt-in, conforme capacidade da GPU/RAM, e nuvem apenas sob gate humano adequado.
7. **Só depois**, construir a interface/mini-layout com Claude e as skills, conectada ao núcleo já testado.

## Limitações

Este PR não substitui `toolkit_doctor`, `pathguard`, `openat2`, SRT, controle efetivo de filesystem, ledger de gastos ou proteção de credenciais. `STRONG=UNAVAILABLE`, operações de arquivo para agentes bloqueadas e `agent_execution_authorized=false`. A vulnerabilidade de leitura por hardlinks nativos continua conhecida; bind mounts reais continuam sem teste. Não cria agentes Claude, hooks, MCP, worktrees, contas, redes ou autenticação. Não toca em `docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256`, `.claude/`, PR #9, outros projetos ou sandbox histórico.

## Testes

Na branch limpa do toolkit (Fish):

```fish
python3 -I -m unittest discover -s tests -p 'test_agent_task_policy.py' -v
python3 scripts/agent_task_policy.py --synthetic-only --json
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
```

**Validação prévia da implementação em ambiente de desenvolvimento isolado:** 28/28 novos testes passaram e a demonstração fictícia manteve todas as autorizações `false`. **Não é evidência de SRT nem de execução de agentes.** O teste no Arch do operador e a auditoria Codex independente ainda estão pendentes.

Antes de eventual merge: testes locais completos, auditoria Codex read-only com revisão dos achados, revisão humana e **nova autorização explícita** para aquele PR.
