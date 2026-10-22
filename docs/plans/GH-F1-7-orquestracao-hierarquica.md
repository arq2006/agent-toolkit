# GH-F1.7 — Orquestração hierárquica e biblioteca de 12 agentes (proposta futura)

Status: **proposta futura registrada em 22/10/2026 a pedido de Arthur; não aprovada para implementação.** Nesta etapa (GH-F1.3) só há estudo de viabilidade. **Não** são criados o `orchestrator` nem os 12 especialistas, e Agent Teams, hooks, MCP e novos agentes continuam fora. Vem **depois** da GH-F1.6 e da auditoria local do Codex, e exigirá aprovação própria. Base: [pesquisa](../pesquisas/claude-code-materializacao-2026-10-22.md), [plano da GH-F1](GH-F1-arquitetura-inicial-agentes.md), [contratos](../contratos/README.md) e [matriz de permissões](../../policies/matriz-riscos-permissoes-aprovacoes.md).

## Arquitetura desejada

| Nível | Papel | Observações |
|---|---|---|
| 1 | Humano + ChatGPT/Claude | Estratégia e planejamento. **Autorização humana obrigatória** para operações sensíveis. ChatGPT é externo: sem integração; só a pessoa leva conteúdo entre as ferramentas, sem dados sensíveis |
| 2 | Claude principal | Coordenação geral da sessão; não é um subagente |
| 3 | `orchestrator` | Seleciona, distribui e supervisiona tarefas de especialistas; **não** aprova, não faz merge |
| 4 | Especialistas (12) | Frontend, Backend, Banco de Dados, DevOps, Segurança, QA, Arquitetura, UI/UX, APIs, Performance, Documentação, Gestão |
| transversal | `planner`, `implementer`, `auditor` | Papéis operacionais reutilizáveis: cada especialista **declara** em qual papel base atua em cada tarefa |
| externo | Codex | Auditor independente quando disponível; **pendente** |

## Viabilidade técnica (a partir da documentação oficial)
- **Hierarquia de subagentes é suportada** até três camadas abaixo da conversa principal (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, padrão 3); o desenho Claude principal → `orchestrator` → especialista usa 2 camadas e deixa folga. Impedir aninhamento adicional nos especialistas (`Agent` fora de `tools`).
- **Sem Agent Teams:** equipes são experimentais, não aninham e custam mais tokens; a hierarquia aqui é de subagentes.
- O `orchestrator` precisa da ferramenta `Agent` e, para restringir quais tipos pode chamar, a lista tipada `Agent(tipo1, tipo2)` só vale quando ele roda como *thread* principal (`claude --agent orchestrator`); como subagente a lista é ignorada. Decidir na GH-F1.7 qual forma adotar.
- **Orçamento de descrições:** 15 definições (12 + 3, mais o `orchestrator`) aproximam o limite de ~15 mil tokens de descrições; manter descrições curtas.
- **Isolamento de escrita:** especialistas que escrevem precisam de worktree própria (`isolation: worktree`) e arquivos reservados; dois especialistas nunca compartilham arquivo.
- **Permissões:** o modo é herdado da sessão principal em alguns casos; a restrição real vem de `tools`/`disallowedTools` e regras `deny`. Subagentes **não veem** o histórico: cada delegação precisa levar escopo, regras, aprovações e estado Git.
- **Aprovação não se propaga:** mensagens entre agentes não concedem aprovação; `action_authorizations` continuam humanas e por ação.
- Conclusão: **viável como subagentes hierárquicos**, começando pequeno. Sugestão de piloto: `orchestrator` + 2 ou 3 especialistas (por exemplo QA, Segurança, Documentação) em tarefas somente de leitura, antes de qualquer escrita.

## Sobreposições a resolver antes de criar a biblioteca
- **Gestão** e **Arquitetura** × `planner`: definir se são especializações do `planner` (leitura/planejamento) ou papéis distintos.
- **QA** e **Segurança** × `auditor`: a auditoria independente é do Codex; QA/Segurança Claude seriam revisão adicional. Segurança técnica e compliance jurídico seguem separados (ADR-008).
- **DevOps**, **Banco de Dados** e **Performance** tocam áreas A3 (produção, banco, storage): somente leitura/proposta enquanto não houver procedimento separado e aprovação específica.
- Cada especialista = domínio + `base_role` (planner/implementer/auditor) + limites; nenhum especialista amplia permissões acima do papel base.

## Extensões de contrato necessárias (a definir quando aprovada)
Campos novos no contrato de agente: `base_role`, `domain`, `delegation` (quem pode delegar a quem, profundidade máxima), `isolation`; no contrato de tarefa: `delegated_to`, `parent_task`. Mudanças que ampliem permissões seguem a regra MAJOR.

## Riscos
- Propagação de *prompt injection* entre camadas; escalonamento de privilégios por delegação; explosão de custo (muitos agentes, esforço elevado); perda de contexto entre camadas; delegação não determinística (decidida pela `description`); sobreposição de papéis; falsa sensação de auditoria independente. Mapear em novos itens da matriz (RK) quando aprovada.

## Critérios para aprovar a GH-F1.7
1. GH-F1.4 a F1.6 concluídas com evidências, e auditoria local do Codex realizada **ou** registrada como pendente por decisão de Arthur.
2. Piloto de leitura do `orchestrator` com 2 a 3 especialistas, sem escrita.
3. Contratos estendidos, matriz atualizada e custo medido.

## O que NÃO é feito agora
Não criar `orchestrator` nem especialistas, não materializar em `.claude/`, não ativar Agent Teams, hooks ou MCP, não mexer em sandbox nem em outros repositórios.
