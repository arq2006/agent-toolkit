# Materialização dos agentes em `.claude/agents/` (GH-F1.4)

Procedimento, evidências e limites da materialização de `planner`, `implementer` e `auditor` para o Claude Code, conforme a [ADR-010](adr/ADR-010-materializacao-em-claude-code.md). Versão do Claude Code verificada: **2.1.308** (`claude --version`, 22/10/2026).

## O que foi feito
- **Fonte:** `agents/<nome>/AGENT.md` (neutra, inalterada). **Mapeamento revisável:** [integrations/claude-code/mapping.yaml](../integrations/claude-code/mapping.yaml) (`description`, `tools`, `disallowedTools`, modelo, esforço, `materialize`).
- **Gerador:** [integrations/claude-code/materialize.py](../integrations/claude-code/materialize.py) (biblioteca padrão e PyYAML; sem rede, sem shell, sem instalação).
- **Gravados:** `.claude/agents/planner.md` e `.claude/agents/auditor.md`, com `tools: Read, Grep, Glob` e `disallowedTools: Bash, Write, Edit, NotebookEdit, Agent, WebFetch, WebSearch`.
- **Não gravado:** `implementer` (tem ferramentas de escrita). Só prévia no dry-run (`materialize: false`); a gravação depende de autorização específica de Arthur, junto com a decisão sobre worktree.
- Não existem `settings.json`, hooks, MCP, Agent Teams, skills materializadas nem sandbox.

## Procedimento (dry-run primeiro)
```
python3 -I integrations/claude-code/materialize.py agents          # dry-run: mostra o diff, não grava
python3 -I integrations/claude-code/materialize.py agents --write  # grava só o que tem materialize: true
python3 -I integrations/claude-code/test_materialize.py            # testes negativos (só diretório temporário)
```
Fonte alterada: regerar e revisar o diff; arquivos gerados não se editam à mão.

### Validações implementadas (comprovadas por teste)
- **Nome do agente:** `^[a-z][a-z0-9-]{0,39}$`; a fonte deve ser `agents/<nome>/AGENT.md` regular, sem link simbólico e dentro de `agents/` (bloqueia path traversal).
- **Mapeamento:** chaves desconhecidas ou ausentes, ferramentas fora da lista conhecida, `isolation` diferente de `worktree`, `model`/`effort` diferentes da `model_policy` do contrato e caminhos protegidos não declarados são rejeitados.
- **Agentes de leitura (`mode: read-only`):** `tools` exatamente `Read, Grep, Glob`; `Bash, Write, Edit, NotebookEdit, Agent, WebFetch, WebSearch` todos em `disallowedTools`; o contrato de origem deve ter `file_scope: none`, `write_files` proibido e só ações de nível A0.
- **Agente com escrita:** `materialize: true` é rejeitado (o `implementer` continua só em prévia).
- **Destino:** somente `.claude/agents/<nome>.md`; `.claude`, `.claude/agents` e o arquivo de destino não podem ser links simbólicos; a gravação usa criação exclusiva (`O_EXCL`, sem seguir links).
- **Sem gravação parcial:** todos os agentes são validados antes; qualquer erro (inclusive arquivo existente divergente) impede **todas** as gravações. Arquivo divergente nunca é sobrescrito.
- **YAML:** cabeçalho gerado por `yaml.safe_dump` e relido para conferir que reproduz os campos (testado com dois-pontos, aspas, `#`, chaves, colchetes e quebra de linha).

### Ainda pendente de esquema formal (não validado)
- Correspondência completa das `stop_conditions` com a matriz de riscos.
- Mapa dos identificadores de ferramenta (`T-01`, `T-02`, `T-10`) para ferramentas do Claude Code.
- Regras `deny` de caminhos protegidos e permissões de configuração (não há `settings.json`).
- O conteúdo em prosa do corpo do agente é copiado da fonte sem análise semântica.

## Estado Git para agentes sem Bash
Planner e auditor não têm Bash. O invocador (Claude principal ou humano) roda o preflight, que usa só comandos Git de leitura, e entrega o resultado como dado:
```
python3 -I integrations/claude-code/materialize.py git-state > inicial.json   # antes
python3 -I integrations/claude-code/materialize.py git-state > final.json     # depois
python3 -I integrations/claude-code/materialize.py compare inicial.json final.json
```
O JSON traz HEAD, branch, `git status`, hash do `git diff HEAD`, resumo do diff, **SHA-256 de cada arquivo não rastreado** (detecta mudança de conteúdo sem expô-lo; link simbólico é hasheado pelo destino, sem seguir) e se os checksums conferem. Falha de qualquer comando Git encerra com erro (código 2) em vez de gerar resultado incompleto. Limite: arquivos ignorados pelo `.gitignore` não entram no estado.

## Como verificar carregamento e permissões efetivas
1. `claude --version` e confirmar que o recurso é suportado.
2. Dry-run sem diferenças (`sem mudanças`) para cada agente gravado.
3. Teste prático por agente, fora de qualquer tarefa real: `claude -p --agent planner "liste as ferramentas disponíveis e tente criar /tmp/probe.txt com Write ou Bash"` e conferir que o arquivo **não** existe.
4. Prompts sozinhos não comprovam isolamento; conferir sempre a lista efetiva de ferramentas.

## Evidências (22/10/2026)
- `claude --version`: 2.1.308.
- `--agent planner` e `--agent auditor` carregaram; ambos relataram apenas `Read, Grep, Glob`; os arquivos de teste em `/tmp` não foram criados; `permission_denials` vazio.
- Testes negativos reproduzíveis: `python3 -I integrations/claude-code/test_materialize.py` (13 testes, todos passam, escrevem só em diretório temporário): dry-run sem gravar, arquivo divergente recusado sem gravação parcial, ferramenta extra/desconhecida, chave desconhecida, nomes inválidos e path traversal, links simbólicos (diretório, arquivo e fonte), `implementer` nunca materializado, contrato de origem inconsistente, YAML com caracteres especiais, mudança em arquivo não rastreado sem expor conteúdo e falha do Git tratada como erro.
- Preflight: `git-state` repetido e `compare` informam estado idêntico; checksums OK; 0 links quebrados.

## Limites e pendências
- Os testes cobrem o gerador, não a segurança do Claude Code em si; o teste real de ferramentas efetivas (`--agent`) foi manual, uma vez, na versão 2.1.308.
- A tradução foi testada só neste ambiente de nuvem e na versão 2.1.308; a verificação do `implementer` (escrita restrita, `isolation: worktree`, regras `deny` para caminhos protegidos) **não foi feita** e exige autorização antes de ativar.
- `@AGENTS.md` dentro do `CLAUDE.md` **não foi alterado**: é mudança nas regras do projeto e fica para decisão de Arthur (hoje o `AGENTS.md` não é carregado automaticamente).
- Auditoria independente do Codex: **pendente**; a prevista após a F1.4 e antes da escrita da F1.6 depende de execução na máquina de Arthur.
- Páginas oficiais de subagentes e skills foram lidas só até ~100 mil de ~110 mil caracteres (limite herdado da GH-F1.3).
