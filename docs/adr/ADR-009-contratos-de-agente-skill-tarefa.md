# ADR-009 — Contratos de agente, skill e tarefa

**Status:** proposta (GH-F1.1, 22/10/2026; aguarda revisão humana do PR)

## Contexto
A GH-F1 exige contratos antes de qualquer agente ou skill ([plano](../plans/GH-F1-arquitetura-inicial-agentes.md), [ADR-007](ADR-007-arquitetura-de-diretorios.md)). O PDF define o contrato de agente (escopo, entradas, saídas, condições de parada) e o fluxo de tarefa; faltava formalizar os campos e a ligação com a matriz de permissões.

## Decisão
1. Três contratos documentados em [docs/contratos/](../contratos/README.md): agente, skill e tarefa, versão 0.1.0.
2. Fonte neutra em Markdown com cabeçalho YAML; campos específicos de ferramenta apenas em `adapters`/`metadata`.
3. Permissões referenciam os níveis A0 a A3 da matriz; contrato nunca excede a matriz; ferramentas devem constar no inventário com estado compatível.
4. Skills seguem a [especificação Agent Skills](https://agentskills.io/specification): `SKILL.md` com `name` (igual ao diretório) e `description`; `metadata` somente com valores string; listas e objetos do contrato ficam em `contract.yaml` ao lado do `SKILL.md`. Validar separadamente YAML, conformidade com Agent Skills e contrato do toolkit. A materialização é verificada na GH-F1.3.
5. Tarefa: `approved_by: null` (e demais campos de aprovação) só em `proposta`; `aprovada` exige aprovador humano, data, referência e escopo; push, PR e merge têm autorizações específicas por ação.
6. Política de modelo: Sonnet com esforço médio por padrão, elevação registrada por tarefa.
7. O auditor Claude em contexto separado não substitui o Codex; a auditoria do Codex segue **pendente**.
8. Validação nesta fase é manual (checklists); nenhum validador, agente ou skill é criado.

## Consequências
- GH-F1.2 pode escrever as definições dos três agentes a partir do contrato.
- Esquema formal (ex.: JSON Schema) e validação automatizada ficam para a GH-F1.3/GH-F2, com aprovação.
- Qualquer mudança que amplie permissões é MAJOR e passa por aprovação humana.
