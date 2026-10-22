# Contrato de tarefa

Versão do contrato: 0.1.1 (revisão da GH-F1.3: alvo de `open_pr` e critério de estado Git; ver histórico no [README](README.md)). Cada tarefa delegada a um agente tem um registro; formato final do arquivo a definir (GH-F1.3). Instâncias reais só quando houver tarefas (pilotos GH-F1.5/F1.6 e seguintes). Fluxo: Intake → Preflight → Análise read-only → Plano curto → Reserva de arquivos/worktree → Implementação → Testes → Auditoria independente → Correções → Aprovação humana → Commit/push/PR manual.

## Campos

| Campo | Obrig. | Regra |
|---|---|---|
| `contract_version`, `id` | sim | versão do contrato e id único da tarefa |
| `title`, `objective` | sim | o que e por quê, verificável |
| `requested_by` | sim | pessoa que pediu a tarefa |
| `approved_by`, `approved_at`, `authorization_ref`, `approved_scope` | sim | aprovação humana do plano (ver abaixo). Podem ser `null` (`approved_by: null`) **somente** enquanto `status` = `proposta`; obrigatórios e completos antes de `aprovada`. Nunca de agente |
| `action_authorizations` | sim | lista de autorizações **por ação** (push, PR, merge...); vazia enquanto nada foi autorizado (ver abaixo) |
| `phase` | sim | fase com prefixo (ex.: `GH-F1.1`) |
| `owner` | sim | agente responsável e papel |
| `base_ref` | sim | branch e commit-base verificados |
| `branch` | sim para escrita | **Obrigatória em tarefas com escrita** (`write-scoped`): branch própria, nome em inglês. **Pode ser `null` em tarefas somente de leitura** (`read-only`), desde que `base_ref` (branch e commit) identifique corretamente o estado analisado |
| `worktree` | escrita | caminho da worktree isolada, quando houver escrita paralela ou em piloto |
| `files_reserved` | escrita | arquivos/diretórios com escrita exclusiva; nunca sobrepostos entre tarefas ativas |
| `files_forbidden` | sim | inclui os protegidos (`docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256`) |
| `mode` | sim | `read-only` ou `write-scoped` |
| `permissions` | sim | níveis A0 a A3 por operação, dentro da matriz |
| `approvals_required` | sim | gates humanos (push, PR, merge por PR específico, instalação etc.) |
| `acceptance_criteria` | sim | critérios verificáveis |
| `tests` | sim | validações a executar e resultado esperado |
| `stop_conditions` | sim | da matriz, mais as específicas da tarefa |
| `evidence_required` | sim | relato: resumo, diff, testes, riscos, pendências, comandos |
| `audit` | sim | quem audita; Codex = independente (estado: pendente); auditor Claude em contexto separado = revisão adicional |
| `model_override` | não | elevação de esforço/modelo e motivo |
| `status` | sim | `proposta` → `aprovada` → `em_execucao` → `em_auditoria` → `em_revisao_humana` → `concluida` / `abandonada` |

## Aprovação humana do plano
Enquanto `status: proposta`, `approved_by` (e os demais campos abaixo) podem ser `null`. A transição para `aprovada` só é válida com todos preenchidos por uma **pessoa**:

| Campo | Conteúdo |
|---|---|
| `approved_by` | identidade da pessoa que aprovou (não um agente) |
| `approved_at` | data e hora da aprovação |
| `authorization_ref` | referência verificável da autorização (ex.: mensagem da pessoa na conversa do projeto, com identificador) |
| `approved_scope` | escopo aprovado: fase, objetivo, arquivos reservados, modo e permissões; o que não consta do escopo não está aprovado |

Mudança de escopo depois da aprovação volta a tarefa para `proposta` (nova aprovação). Um agente nunca preenche `approved_by`.

## Autorizações específicas por ação (`action_authorizations`)
A aprovação do plano **não** autoriza push, abertura de PR nem merge. Cada ação sensível exige uma autorização própria, registrada como item da lista:

| Campo | Conteúdo |
|---|---|
| `action` | `push`, `open_pr`, `mark_ready` ou `merge` (uma por item) |
| `target` | alvo específico. `push`: repositório e branch. `open_pr` (PR ainda inexistente): **repositório, branch head e branch base**, sem número. `mark_ready` e `merge` (PR já existe): repositório e **número do PR**, com o commit head esperado. Depois de criado, o número do PR pode ser anotado no item de `open_pr` |
| `authorized_by`, `authorized_at`, `authorization_ref` | pessoa, data e referência verificável |
| `scope` | limites da autorização (ex.: head verificado, "somente este PR") |

Regras: uma autorização vale **só** para a ação e o alvo registrados; `mark_ready` e `merge` exigem o número do PR e o commit head esperado (o PR precisa existir); autorizar `open_pr` não autoriza `merge`; autorização de um PR não vale para outro; execução delegada ao Claude segue a [matriz](../../policies/matriz-riscos-permissoes-aprovacoes.md); alteração de proteção de branch não é ação de tarefa e exige autorização especial fora deste contrato.

## Regras
1. **Reserva exclusiva:** duas tarefas com escrita nunca reservam o mesmo arquivo; colisão interrompe a execução e é relatada.
2. **Preflight obrigatório:** conferir branch, HEAD e estado do Git (em tarefa de leitura com `branch: null`, o `base_ref` com commit identifica o estado analisado); checksums dos documentos importados; escopo contra a reserva.
3. **Aprovação não se herda:** a aprovação de uma tarefa não cobre outra, nem outra fase, nem push, PR ou merge (cada um tem autorização própria), nem merge de PR diferente.
4. **Relato padronizado:** todo término entrega arquivos tocados, testes, riscos, pendências e evidências; sem isso a tarefa não vai a `em_revisao_humana`.
5. **Merge:** só com autorização humana específica para o PR (item em `action_authorizations`); a execução pode ser delegada ao Claude conforme a matriz. Proteção de branch fica fora de qualquer tarefa comum.
6. **Isolamento comprovado:** permissões efetivas das ferramentas são verificadas; prompt sozinho não prova isolamento de escrita.

## Exemplo ilustrativo (fictício)

```yaml
contract_version: 0.1.1
id: TASK-EXEMPLO-001
title: Resumir estrutura de repositório descartável
objective: Produzir resumo da estrutura sem alterar arquivos.
requested_by: <pessoa>
approved_by: null          # null permitido somente enquanto status = proposta
approved_at: null
authorization_ref: null
approved_scope: null
action_authorizations: []
phase: GH-F1.5
owner: {agent: planner, role: read-only}
base_ref: {branch: main, commit: <sha>}
branch: null
files_reserved: []
files_forbidden: [docs/references/, docs/security/, docs/CHECKSUMS.sha256]
mode: read-only
permissions: [{op: read_repository, level: A0}]
approvals_required: []
acceptance_criteria: ["Nenhum arquivo alterado", "Resumo cita caminhos lidos"]
tests: ["estado Git ao final idêntico ao inicial (HEAD, branch, status, diff)"]
stop_conditions: [instruction_in_external_content, scope_exceeded]
evidence_required: [summary, risks, pending, commands]
audit: {independent: codex (pendente), additional: claude-separate-context}
status: proposta
```

Fragmento de uma tarefa já `aprovada`, com uma autorização de PR específica (valores fictícios):

```yaml
status: aprovada
approved_by: <pessoa>
approved_at: AAAA-MM-DDTHH:MM:SSZ
authorization_ref: <mensagem ou registro verificável>
approved_scope: "GH-F1.5; leitura somente; sem arquivos reservados; permissões A0"
action_authorizations:
  - action: open_pr
    target: {repository: <repo>, head: <branch-head>, base: <branch-base>}   # PR ainda não existe: sem número
    authorized_by: <pessoa>
    authorized_at: AAAA-MM-DDTHH:MM:SSZ
    authorization_ref: <referência>
    scope: "um PR em rascunho entre essas branches"
```

## Checklist de revisão
- [ ] `approved_by: null` (e demais campos de aprovação nulos) somente com `status: proposta`; para `aprovada`, aprovador humano, data, referência e escopo aprovado preenchidos.
- [ ] Push, PR e merge têm itens próprios em `action_authorizations`, cada um com alvo e escopo; nenhuma autorização herdada.
- [ ] Fase e base verificadas.
- [ ] Reserva sem sobreposição; protegidos em `files_forbidden`.
- [ ] Permissões ≤ matriz; gates humanos listados.
- [ ] Critérios, testes e evidências verificáveis; auditoria declarada com o estado real do Codex.
