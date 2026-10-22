# Contrato de tarefa

Versão do contrato: 0.1.0 (rascunho). Cada tarefa delegada a um agente tem um registro; formato final do arquivo a definir (GH-F1.3). Instâncias reais só quando houver tarefas (pilotos GH-F1.5/F1.6 e seguintes). Fluxo: Intake → Preflight → Análise read-only → Plano curto → Reserva de arquivos/worktree → Implementação → Testes → Auditoria independente → Correções → Aprovação humana → Commit/push/PR manual.

## Campos

| Campo | Obrig. | Regra |
|---|---|---|
| `contract_version`, `id` | sim | versão do contrato e id único da tarefa |
| `title`, `objective` | sim | o que e por quê, verificável |
| `requested_by` / `approved_by` | sim | pessoa que pediu e que aprovou o plano; **aprovação humana, nunca de agente** |
| `phase` | sim | fase com prefixo (ex.: `GH-F1.1`) |
| `owner` | sim | agente responsável e papel |
| `base_ref` | sim | branch e commit-base verificados |
| `branch` | sim | branch própria, nome em inglês |
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

## Regras
1. **Reserva exclusiva:** duas tarefas com escrita nunca reservam o mesmo arquivo; colisão interrompe a execução e é relatada.
2. **Preflight obrigatório:** conferir branch, HEAD e estado do Git; checksums dos documentos importados; escopo contra a reserva.
3. **Aprovação não se herda:** a aprovação de uma tarefa não cobre outra, nem outra fase, nem merge de PR diferente.
4. **Relato padronizado:** todo término entrega arquivos tocados, testes, riscos, pendências e evidências; sem isso a tarefa não vai a `em_revisao_humana`.
5. **Merge:** só com autorização humana específica para o PR; a execução pode ser delegada ao Claude conforme a matriz. Proteção de branch fica fora de qualquer tarefa comum.
6. **Isolamento comprovado:** permissões efetivas das ferramentas são verificadas; prompt sozinho não prova isolamento de escrita.

## Exemplo ilustrativo (fictício)

```yaml
contract_version: 0.1.0
id: TASK-EXEMPLO-001
title: Resumir estrutura de repositório descartável
objective: Produzir resumo da estrutura sem alterar arquivos.
requested_by: <pessoa>
approved_by: <pessoa>
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
tests: ["git status limpo ao final"]
stop_conditions: [instruction_in_external_content, scope_exceeded]
evidence_required: [summary, risks, pending, commands]
audit: {independent: codex (pendente), additional: claude-separate-context}
status: proposta
```

## Checklist de revisão
- [ ] Aprovação humana registrada; fase e base verificadas.
- [ ] Reserva sem sobreposição; protegidos em `files_forbidden`.
- [ ] Permissões ≤ matriz; gates humanos listados.
- [ ] Critérios, testes e evidências verificáveis; auditoria declarada com o estado real do Codex.
