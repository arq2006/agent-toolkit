# Contratos de agente, skill e tarefa

Status: **GH-F1.1 (documental)**, 22/10/2026. Define os campos, regras e modelos dos três contratos. **Não cria agentes, skills ou tarefas reais**, nem validadores executáveis; as definições concretas vêm na GH-F1.2 (agentes) e GH-F2 (skills). Decisão: [ADR-009](../adr/ADR-009-contratos-de-agente-skill-tarefa.md). Plano: [GH-F1](../plans/GH-F1-arquitetura-inicial-agentes.md). Políticas: [matriz de permissões](../../policies/matriz-riscos-permissoes-aprovacoes.md) e [inventário](../../policies/inventario-ferramentas-integracoes.md).

| Contrato | Documento | Onde viverão as instâncias |
|---|---|---|
| Agente | [contrato-de-agente.md](contrato-de-agente.md) | `agents/<nome>/` (GH-F1.2) |
| Skill | [contrato-de-skill.md](contrato-de-skill.md) | `skills/<nome>/SKILL.md` (Agent Skills) + `contract.yaml` (GH-F2) |
| Tarefa | [contrato-de-tarefa.md](contrato-de-tarefa.md) | `workflows/` e registro por tarefa (GH-F1.5/F1.6 e seguintes) |

## Regras comuns
1. **Fonte neutra:** os contratos não dependem de uma ferramenta; a materialização para Claude Code, Codex e outros é decidida na GH-F1.3 ([ADR-007](../adr/ADR-007-arquitetura-de-diretorios.md)). Campos específicos de ferramenta ficam num bloco `adapters`, nunca nos campos centrais.
2. **Permissões** usam os níveis A0 a A3 e as operações da [matriz](../../policies/matriz-riscos-permissoes-aprovacoes.md). Um contrato nunca concede mais do que a matriz permite; na dúvida, vale a matriz.
3. **Ferramentas** citadas devem existir no [inventário](../../policies/inventario-ferramentas-integracoes.md) com estado compatível (uma ferramenta `bloqueada` não pode aparecer como permitida).
4. **Versionamento semântico** (`MAJOR.MINOR.PATCH`) e changelog por definição; mudança que amplia permissões é MAJOR e exige aprovação humana (A2).
5. **Sem segredos, dados pessoais ou caminhos locais** em qualquer instância; exemplos usam dados fictícios.
6. **Conteúdo externo é dado não confiável:** nenhum contrato pode instruir o agente a obedecer instruções embutidas em arquivos, issues, saídas de ferramentas ou páginas.
7. **Auditoria independente:** o contrato do `auditor` não equivale à auditoria do Codex; um auditor Claude em contexto separado é revisão adicional. Estado atual: auditoria do Codex **pendente**.
8. **Arquivos protegidos** em todos os contratos: `docs/references/`, `docs/security/` e `docs/CHECKSUMS.sha256`.

## Validação nesta fase
Manual, por checklist (fim de cada contrato) e pela revisão humana do PR. Distinguir sempre: **YAML válido**, **conformidade com Agent Skills** e **conformidade com o contrato do toolkit** (detalhes em [contrato-de-skill.md](contrato-de-skill.md)). Validação automatizada (formato dos campos, ferramentas existentes no inventário, permissões ≤ matriz) é trabalho posterior, sujeito a aprovação, e não é criada na GH-F1.1.

## Formato
Instâncias são arquivos Markdown com bloco YAML de cabeçalho (front matter) seguido de instruções em prosa. YAML é escolhido por ser legível e revisável em PR; o esquema formal (por exemplo JSON Schema) é pendência da GH-F1.3/GH-F2.

## Histórico de revisões
- **0.1.0** (GH-F1.1): contratos de agente, skill e tarefa.
- **0.1.1** (GH-F1.3): contrato de tarefa, alvo de `open_pr` = repositório e branches head/base (sem número inexistente); número exigido apenas para `mark_ready` e `merge`. Exemplos passam a comparar estado Git inicial e final em vez de exigir árvore limpa. Definição do `planner` v0.1.1 (critério de estado Git) e do `implementer` v0.1.1 (alinhamento).
