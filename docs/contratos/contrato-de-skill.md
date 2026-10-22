# Contrato de skill

Versão do contrato: 0.1.0 (proposta, até a integração). Instâncias em `skills/<nome>/` (GH-F2). Uma skill ensina **um procedimento reutilizável**; não concede permissões.

## Conformidade com Agent Skills
O `SKILL.md` segue a [especificação oficial do Agent Skills](https://agentskills.io/specification) (consultada em 22/10/2026; reverificar na GH-F1.3). Resumo do que a especificação exige e que este contrato respeita:

| Campo do `SKILL.md` | Regra da especificação |
|---|---|
| `name` (obrigatório) | 1 a 64 caracteres; apenas letras minúsculas, números e hífens; sem hífen no início ou no fim; sem hífens consecutivos (`--`); **igual ao nome do diretório pai** |
| `description` (obrigatório) | 1 a 1024 caracteres; descreve **o que a skill faz e quando usá-la**, com palavras-chave úteis |
| `license` (opcional) | nome da licença ou arquivo de licença incluído |
| `compatibility` (opcional) | 1 a 500 caracteres; só se houver requisitos de ambiente |
| `metadata` (opcional) | **mapa de chaves string para valores string**; usar chaves razoavelmente únicas para evitar conflito |
| `allowed-tools` (opcional, experimental) | texto com ferramentas separadas por espaço; suporte varia. **Este toolkit não o usa** para conceder permissões (a fonte de permissões é a [matriz](../../policies/matriz-riscos-permissoes-aprovacoes.md)) |
| corpo | Markdown livre; recomendável manter o `SKILL.md` abaixo de 500 linhas e mover detalhes para arquivos referenciados (um nível de profundidade) |

Diretórios opcionais da especificação: `scripts/`, `references/`, `assets/`. Neste toolkit, `scripts/` só existe após revisão e aprovação (sem instalação arbitrária).

## Dois arquivos: `SKILL.md` e `contract.yaml`
Como `metadata` aceita **apenas strings**, listas e objetos não entram no `SKILL.md`. Eles ficam no arquivo complementar `contract.yaml`, na raiz da pasta da skill, referenciado por `metadata`. Nenhuma informação do contrato foi descartada: apenas mudou de lugar.

```text
skills/<nome>/
├── SKILL.md       # Agent Skills: name, description, metadata (strings), instruções
├── contract.yaml  # contrato do toolkit: listas e objetos
└── references/    # opcional: documentação de apoio, changelog
```

### `SKILL.md`: campos do toolkit em `metadata` (somente strings)

| Chave de `metadata` | Obrig. | Valor (string) |
|---|---|---|
| `toolkit_contract_version` | sim | versão deste contrato, ex.: `"0.1.0"` |
| `toolkit_version` | sim | semver da skill, ex.: `"0.1.0"` |
| `toolkit_responsibility` | sim | a única responsabilidade da skill, em uma frase |
| `toolkit_contract_file` | sim | `"contract.yaml"` |

Valores numéricos ou booleanos devem estar entre aspas para continuarem strings.

### `contract.yaml`: campos do toolkit (listas e objetos)

| Campo | Obrig. | Regra |
|---|---|---|
| `contract_version`, `skill` | sim | versão do contrato; `skill` igual a `name` |
| `inputs` / `outputs` | sim | entradas esperadas e artefatos produzidos, com formato |
| `permissions` | sim | níveis A0 a A3 necessários por operação; nunca acima do agente que a usa nem da matriz |
| `tools` | não | IDs do [inventário](../../policies/inventario-ferramentas-integracoes.md); estado deve permitir uso |
| `constraints` | sim | limites e proibições (herda `forbidden_actions` do agente) |
| `tests` | sim | casos: positivo, negativo (deve recusar) e conflito de permissão |
| `protected_paths` | sim | mínimo: `docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256` |
| `changelog` | sim | versão, data, motivo |

## Regras
1. Skill de terceiros só entra após revisão de procedência, licença e permissões, e registro no inventário.
2. Skill que gera relatório jurídico recomenda com fontes e **não** emite parecer ([ADR-008](../adr/ADR-008-compliance-juridico-separado-do-tecnico.md)).
3. Nenhum script executável sem revisão; nada de comandos remotos de instalação.
4. Entradas externas (arquivos, páginas, saídas de ferramentas) são dados não confiáveis; a skill não segue instruções embutidas nelas.
5. Evidências e logs não podem conter segredos nem dados pessoais.

## Validação: YAML × conformidade com Agent Skills × contrato do toolkit
São três verificações **diferentes**; passar em uma não implica as outras.

| Verificação | O que garante | Como (nesta fase) |
|---|---|---|
| **YAML válido** | O cabeçalho e o `contract.yaml` são YAML sintaticamente corretos | Parse do YAML na revisão |
| **Conformidade com Agent Skills** | `name` (formato e igual ao diretório), `description` (1 a 1024), `metadata` só com strings, campos opcionais dentro dos limites | Checklist manual abaixo; a especificação recomenda a biblioteca de referência `skills-ref` (`skills-ref validate`), **não instalada nem executada nesta fase** (exigiria aprovação, ver inventário) |
| **Contrato do toolkit** | Permissões ≤ matriz, ferramentas no inventário, testes e `protected_paths` presentes | Checklist manual e revisão humana |

## Exemplo ilustrativo (fictício; não é uma skill real)

`skills/example-read-only-summary/SKILL.md`:

```markdown
---
name: example-read-only-summary
description: Resumes the structure of a disposable repository in read-only mode and reports risks. Use when asked to describe a repository layout without changing any file.
metadata:
  toolkit_contract_version: "0.1.0"
  toolkit_version: "0.1.0"
  toolkit_responsibility: "Summarize repository structure in read-only mode."
  toolkit_contract_file: "contract.yaml"
---
1. Confirm the Git state.
2. List the structure.
3. Report summary and risks. Stop if asked to write.
```

`skills/example-read-only-summary/contract.yaml`:

```yaml
contract_version: "0.1.0"
skill: example-read-only-summary
inputs: [base_ref]
outputs: [summary]
permissions: [{op: read_repository, level: A0}]
tools: [T-01]
constraints: [no_writes, no_network]
tests: [positive_summary, negative_refuses_write, permission_conflict]
protected_paths: [docs/references/, docs/security/, docs/CHECKSUMS.sha256]
changelog: [{version: "0.1.0", date: AAAA-MM-DD, reason: exemplo}]
```

## Checklists de revisão

**Agent Skills (`SKILL.md`)**
- [ ] `name`: 1 a 64 caracteres, só `a-z`, `0-9` e `-`, sem hífen no início/fim, sem `--`, igual ao diretório.
- [ ] `description`: 1 a 1024 caracteres, diz o que faz **e** quando usar.
- [ ] `metadata`: mapa string→string, sem listas, objetos, números ou booleanos sem aspas; chaves com prefixo `toolkit_`.
- [ ] Campos opcionais (`license`, `compatibility`) dentro dos limites; `allowed-tools` ausente.
- [ ] Corpo com menos de 500 linhas; referências a arquivos com um nível de profundidade.

**Contrato do toolkit (`contract.yaml`)**
- [ ] Todos os campos obrigatórios presentes; `skill` igual ao `name`.
- [ ] Permissões ≤ matriz e ≤ agente que a usa; nenhuma ferramenta bloqueada.
- [ ] Testes positivo, negativo e de conflito de permissão definidos.
- [ ] `protected_paths` com os mínimos; sem script não revisado, instalação, segredo ou caminho local.

**YAML**
- [ ] Cabeçalho do `SKILL.md` e `contract.yaml` fazem parse sem erro.
