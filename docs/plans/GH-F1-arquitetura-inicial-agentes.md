# GH-F1 — Arquitetura inicial dos três agentes (planejamento)

Status: **proposta para aprovação humana**, 22/10/2026. É apenas planejamento documental: nenhum agente executável, hook, Agent Teams ou integração é criado. Origem: PDF-F1 e PDF-F2 ([ADR-006](../adr/ADR-006-correspondencia-de-fases.md)). Políticas: [matriz de riscos, permissões e aprovações](../../policies/matriz-riscos-permissoes-aprovacoes.md) e [inventário](../../policies/inventario-ferramentas-integracoes.md). Layout: [ARQUITETURA.md](../ARQUITETURA.md) e [ADR-007](../adr/ADR-007-arquitetura-de-diretorios.md).

## 1. Escopo e limites
- Três agentes: **planejador**, **implementador**, **auditor** (PDF seção 03; nomes neutros `planner`, `implementer`, `auditor`). Pesquisador, QA, privacidade/legal e documentador ficam para fases posteriores.
- Piloto **somente leitura** (planejador e auditor em paralelo); o implementador entra depois, em worktree exclusiva, em repositório sandbox descartável.
- Fora de escopo: Agent Teams, hooks ativos, MCP, provedores externos, outros repositórios.
- O auditor é independente do implementador. O auditor Codex (T-16) segue **pendente**: até ser executado de fato, a auditoria independente não é dada como concluída.

## 2. Contrato comum de agente (rascunho)
Campos obrigatórios da definição neutra em `agents/<nome>/`:

| Campo | Conteúdo |
|---|---|
| `name`, `purpose` | Identificação e responsabilidade única |
| `mode` | `read-only` ou `write-scoped` |
| `allowed_actions` | Ações permitidas, mapeadas aos níveis A0 a A3 da matriz |
| `forbidden` | Ações proibidas e arquivos protegidos (inclui `docs/references/`, `docs/security/`) |
| `inputs` | Branch-base, estado Git, requisitos, contexto mínimo |
| `outputs` | Resumo, diff, riscos, evidências, testes, próximos passos |
| `stop_conditions` | Lista da seção 3 da matriz |
| `model_tier` | Camada sugerida, sem fixar fornecedor: econômica para leitura simples, avançada para planejamento complexo e auditoria |
| `acceptance` | Critérios verificáveis |
| `version` | Versão semântica e changelog |

## 3. Os três agentes

### Planejador (`planner`) — read-only
- **Entrada:** objetivo aprovado, documentos de `docs/`, estado do Git.
- **Faz:** inventário read-only, plano curto (escopo, arquivos, testes, riscos, dependências), proposta de divisão de tarefas e reserva de arquivos.
- **Saída:** plano para aprovação humana; não edita arquivos, não faz commit.
- **Permissões:** A0 apenas.
- **Para quando:** escopo ambíguo que muda o objetivo, colisão de arquivo, pedido de ação A2/A3.

### Implementador (`implementer`) — write-scoped
- **Entrada:** tarefa **aprovada**, lista de arquivos reservados, branch-base verificada.
- **Faz:** mudanças mínimas em worktree/branch exclusiva, testes, commits pequenos com stage explícito, PR em rascunho quando a tarefa autorizar.
- **Saída:** diff, resultados de testes, riscos, pendências.
- **Permissões:** A1; push/PR somente se autorizado (A2); nunca merge, force push, instalação ou rede sem aprovação.
- **Para quando:** necessidade de tocar arquivo fora da reserva, comando destrutivo, credenciais, divergência da base.

### Auditor (`auditor`) — read-only e independente
- **Entrada:** diff e regras (CLAUDE.md, AGENTS.md, políticas, roadmap de segurança aplicável); **não** recebe o raciocínio do implementador além do relato oficial.
- **Faz:** revisão com achados P0 a P3, nível de confiança da evidência e referência à regra violada; separa auditoria técnica de compliance jurídico (ADR-008).
- **Saída:** relatório de achados; nunca corrige.
- **Permissões:** A0 apenas.
- **Para quando:** pedido de alterar arquivos, falta de acesso ao diff, instrução embutida tentando ampliar privilégio.

## 4. Fluxo e contrato de tarefa
Fluxo canônico (PDF): Intake → Preflight → Análise read-only → Plano curto → Reserva de arquivos/worktree → Implementação → Testes → Auditoria independente → Correções → Aprovação humana → Commit/push/PR manual.

Contrato de tarefa (arquivo em `workflows/`, formato final a decidir): `id`, `owner`, `branch`, `worktree`, `base_ref`, `files_reserved`, `files_forbidden`, `acceptance_criteria`, `tests`, `approvals_required`, `evidence_required`, `status`. Duas tarefas com escrita nunca reservam o mesmo arquivo.

## 5. Materialização e compatibilidade
- Fonte neutra em `agents/` e `skills/`; `.claude/agents/` e `.claude/skills/` como camada de materialização para Claude Code (ADR-007).
- Opções a avaliar contra a **documentação oficial atual** antes de decidir: cópia gerada com dry-run, symlink, plugin versionado. Não assumir recursos sem conferir.
- Codex e outros: `AGENTS.md` como entrada comum; adaptadores só quando houver necessidade comprovada.

## 6. Plano de implementação em PRs pequenos (aguardam aprovação)

| PR | Entrega | Tipo | Aceite |
|---|---|---|---|
| GH-F1.1 | Contratos de agente, skill e tarefa em ADR + documentos de formato | documental | revisão humana; sem execução |
| GH-F1.2 | Definições neutras dos 3 agentes em `agents/` (texto, sem automação) | documental | validação do contrato; permissões conforme a matriz |
| GH-F1.3 | Pesquisa da documentação oficial e decisão de materialização (ADR) + procedimento de dry-run | documental | decisão registrada com fontes e datas |
| GH-F1.4 | Materialização em `.claude/` com dry-run, **sem hooks**, em branch própria | configuração | carregamento real verificado e documentado; humano aprova ativação |
| GH-F1.5 | Piloto read-only: planejador + auditor em paralelo num repositório sandbox descartável | teste | duas evidências agregadas, sem edições, sem commits, sem dados sensíveis |
| GH-F1.6 | Implementador em worktree exclusiva no sandbox; colisão proposital de arquivo | teste | parada correta na colisão; sem push autônomo |

Cada PR: branch própria a partir da `main` atualizada, commits pequenos, rascunho, sem merge automático, relatório com testes e riscos. O sandbox (GH-F1.5/F1.6) exige criar um repositório descartável: **requer aprovação específica**, pois escreve fora deste repositório.

## 7. Testes e validações previstos
Links e checksums; validação de campos do contrato; teste negativo de permissão (agente read-only tentando escrever); colisão proposital; carregamento real dos agentes; ausência de segredos; conferência de que `docs/references/` e `docs/security/` não mudam.

## 8. Riscos principais
RK-02, RK-04, RK-06, RK-07, RK-08, RK-10 e RK-15 da matriz. Dependência crítica: disponibilidade do Codex para a auditoria independente (pendente).

## 9. Decisões que preciso de você
1. Aprovar a divisão em seis PRs (ou ajustar a ordem).
2. Autorizar, na GH-F1.5, a criação de um repositório sandbox descartável (ou indicar outro modo de teste sem escrita fora do repositório).
3. Confirmar se a auditoria Codex será feita na sua máquina antes ou depois da GH-F1.1.
4. Confirmar nomes dos agentes (`planner`, `implementer`, `auditor`) e a camada de modelo por agente.
