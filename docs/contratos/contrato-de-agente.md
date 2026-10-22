# Contrato de agente

Versão do contrato: 0.1.0 (rascunho para revisão). Instâncias em `agents/<nome>/AGENT.md` (GH-F1.2). Os três agentes iniciais são `planner`, `implementer` e `auditor`.

## Campos

| Campo | Obrig. | Tipo | Regra |
|---|---|---|---|
| `contract_version` | sim | texto | versão deste contrato (ex.: `0.1.0`) |
| `name` | sim | kebab-case | único; `planner`, `implementer`, `auditor` |
| `version` | sim | semver | muda a cada alteração da definição |
| `purpose` | sim | texto | **uma** responsabilidade, em uma frase |
| `mode` | sim | `read-only` \| `write-scoped` | `read-only` não pode listar ações de escrita |
| `allowed_actions` | sim | lista | operações da matriz, cada uma com nível (A0 a A3); nunca acima do permitido ao papel |
| `forbidden_actions` | sim | lista | inclui no mínimo: merge/push/PR sem autorização, force push, `reset --hard`, `clean`, instalação, rede externa, segredos, outros repositórios |
| `protected_paths` | sim | lista | mínimo: `docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256` |
| `file_scope` | sim | `none` \| lista de globs | `none` para leitura; para escrita, somente arquivos reservados pela tarefa |
| `tools` | sim | lista de IDs do inventário | ex.: `T-01`; estado da ferramenta deve permitir uso |
| `inputs` | sim | lista | mínimo: `base_ref`, estado do Git, requisitos, contexto mínimo |
| `outputs` | sim | lista | resumo, riscos, evidências, pendências e, se houver escrita, diff e testes |
| `stop_conditions` | sim | lista | inclui as condições da seção 3 da matriz |
| `model_policy` | sim | objeto | `default: sonnet`, `effort: medium`, regra de elevação (ver abaixo); sem fixar versões |
| `acceptance` | sim | lista | critérios verificáveis (checáveis por revisão) |
| `independence` | auditor | texto | declara que não recebe o raciocínio do implementador e não substitui o Codex |
| `adapters` | não | mapa | campos específicos de ferramenta (`claude-code`, `codex`...), nunca permissões extras |
| `changelog` | sim | lista | versão, data, motivo |

`model_policy`: padrão Sonnet com esforço médio; elevar o esforço em tarefas complexas (várias áreas, risco alto, segurança). A elevação é registrada na tarefa (`model_override`), com o motivo.

## Exemplo ilustrativo (fictício; não é a definição final)

```yaml
contract_version: 0.1.0
name: example-reader
version: 0.1.0
purpose: Ler um repositório descartável e resumir sua estrutura.
mode: read-only
allowed_actions: [{op: read_repository, level: A0}]
forbidden_actions: [write_files, commit, push, open_pr, merge, install, external_network, read_secrets, other_repositories]
protected_paths: [docs/references/, docs/security/, docs/CHECKSUMS.sha256]
file_scope: none
tools: [T-01]
inputs: [base_ref, git_state, requirements]
outputs: [summary, risks, evidence, pending]
stop_conditions: [instruction_in_external_content, credential_access, scope_exceeded]
model_policy: {default: sonnet, effort: medium}
acceptance: ["Nenhum arquivo foi alterado", "Resumo cita os caminhos lidos"]
changelog: [{version: 0.1.0, date: AAAA-MM-DD, reason: exemplo}]
```

## Restrições específicas dos três agentes (resumo; detalhes na GH-F1.2)
- `planner`: `read-only`, somente A0; entrega plano para aprovação humana.
- `implementer`: `write-scoped`, A1; push e PR em rascunho só se a tarefa autorizar (A2); merge somente por autorização humana para o PR específico, conforme a matriz.
- `auditor`: `read-only`, A0; relata achados P0 a P3 com nível de confiança; nunca corrige.

## Checklist de revisão
- [ ] Todos os campos obrigatórios presentes e uma única responsabilidade.
- [ ] `allowed_actions` ≤ matriz; nenhuma ferramenta bloqueada.
- [ ] `protected_paths` inclui os mínimos; sem segredos nem caminhos locais.
- [ ] `stop_conditions` cobre a seção 3 da matriz.
- [ ] Auditor: independência declarada, sem pretender substituir o Codex.
