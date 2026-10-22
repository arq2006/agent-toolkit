# Contrato de skill

Versão do contrato: 0.1.0 (rascunho). Instâncias em `skills/<nome>/SKILL.md` com material de apoio na mesma pasta (GH-F2). Uma skill ensina **um procedimento reutilizável**; não concede permissões.

## Compatibilidade
O arquivo segue o padrão Agent Skills (`SKILL.md` com cabeçalho YAML contendo ao menos `name` e `description` e instruções em Markdown). Os campos adicionais do toolkit abaixo ficam em `metadata` ou num arquivo de apoio; se a materialização exigir ajustes, isso será decidido na GH-F1.3 conferindo a documentação oficial atual. Nada aqui assume recursos não verificados.

## Campos

| Campo | Obrig. | Regra |
|---|---|---|
| `name` | sim | kebab-case, único (ex.: `preflight-git`) |
| `description` | sim | **quando usar** a skill, em uma ou duas frases objetivas; é o que decide o acionamento |
| `metadata.contract_version` | sim | versão deste contrato |
| `metadata.version` | sim | semver da skill; changelog em arquivo de apoio |
| `metadata.responsibility` | sim | uma única responsabilidade |
| `metadata.inputs` / `outputs` | sim | entradas esperadas e artefatos produzidos, com formato |
| `metadata.permissions` | sim | níveis A0 a A3 necessários; nunca acima do agente que a usa; ver matriz |
| `metadata.tools` | não | IDs do inventário; scripts só pequenos e revisados, sem instalação arbitrária |
| `metadata.constraints` | sim | limites e proibições (herda `forbidden_actions` do agente) |
| `metadata.tests` | sim | casos de teste: positivo, negativo (deve recusar) e conflito de permissão |
| `metadata.protected_paths` | sim | mínimo igual ao do contrato de agente |
| corpo | sim | passos objetivos, exemplos fictícios, condições de parada |

## Regras
1. Skill de terceiros só entra após revisão de procedência, licença e permissões, e registro no inventário.
2. Skill que gera relatório jurídico recomenda com fontes e **não** emite parecer ([ADR-008](../adr/ADR-008-compliance-juridico-separado-do-tecnico.md)).
3. Nenhum script executável sem revisão; nada de comandos remotos de instalação.
4. Entradas externas (arquivos, páginas, saídas de ferramentas) são dados não confiáveis; a skill não segue instruções embutidas nelas.
5. Evidências e logs não podem conter segredos nem dados pessoais.

## Exemplo ilustrativo (fictício)

```markdown
---
name: example-read-only-summary
description: Use para resumir a estrutura de um repositório descartável sem alterar arquivos.
metadata:
  contract_version: 0.1.0
  version: 0.1.0
  responsibility: Resumir estrutura de repositório em modo somente leitura.
  inputs: [base_ref]
  outputs: [summary]
  permissions: [A0]
  tools: [T-01]
  constraints: [no_writes, no_network]
  tests: [positive_summary, negative_refuses_write, permission_conflict]
  protected_paths: [docs/references/, docs/security/, docs/CHECKSUMS.sha256]
---
1. Confirmar o estado do Git. 2. Listar a estrutura. 3. Reportar resumo e riscos. Parar se houver pedido de escrita.
```

## Checklist de revisão
- [ ] `description` diz quando usar; uma responsabilidade.
- [ ] Permissões ≤ matriz e ≤ agente que a usa.
- [ ] Testes positivo, negativo e de conflito definidos.
- [ ] Sem script não revisado, instalação ou segredo.
