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
```
- O gerador **valida** contra o contrato e a matriz: agente `read-only` não pode ter `Bash`, `Write`, `Edit`, `NotebookEdit`, `Agent`, `WebFetch` nem `WebSearch`, e todos devem constar em `disallowedTools`; agente com escrita não é gravado sem autorização.
- **Nunca sobrescreve:** se o arquivo existe e difere, recusa e pede análise humana. Configurações preexistentes em `.claude/` (não havia nenhuma) permanecem intactas.
- Fonte alterada: regerar e revisar o diff; arquivos gerados não se editam à mão.

## Estado Git para agentes sem Bash
Planner e auditor não têm Bash. O invocador (Claude principal ou humano) roda o preflight, que usa só comandos Git de leitura, e entrega o resultado como dado:
```
python3 -I integrations/claude-code/materialize.py git-state > inicial.json   # antes
python3 -I integrations/claude-code/materialize.py git-state > final.json     # depois
python3 -I integrations/claude-code/materialize.py compare inicial.json final.json
```
O JSON traz HEAD, branch, `git status` (inclui não rastreados), hash do `git diff HEAD`, resumo do diff e se os checksums conferem. O agente não ganha permissão alguma. Limite: o hash do diff não cobre o conteúdo de arquivos não rastreados (só seus nomes).

## Como verificar carregamento e permissões efetivas
1. `claude --version` e confirmar que o recurso é suportado.
2. Dry-run sem diferenças (`sem mudanças`) para cada agente gravado.
3. Teste prático por agente, fora de qualquer tarefa real: `claude -p --agent planner "liste as ferramentas disponíveis e tente criar /tmp/probe.txt com Write ou Bash"` e conferir que o arquivo **não** existe.
4. Prompts sozinhos não comprovam isolamento; conferir sempre a lista efetiva de ferramentas.

## Evidências (22/10/2026)
- `claude --version`: 2.1.308.
- `--agent planner` e `--agent auditor` carregaram; ambos relataram apenas `Read, Grep, Glob`; os arquivos de teste em `/tmp` não foram criados; `permission_denials` vazio.
- Teste negativo do gerador: adicionar `Bash` ao planner no mapeamento gera `ERRO` e bloqueia a gravação; arquivo existente alterado gera `RECUSADO`.
- Preflight: `git-state` repetido e `compare` informam estado idêntico; checksums OK; 0 links quebrados.

## Limites e pendências
- A tradução foi testada só neste ambiente de nuvem e na versão 2.1.308; a verificação do `implementer` (escrita restrita, `isolation: worktree`, regras `deny` para caminhos protegidos) **não foi feita** e exige autorização antes de ativar.
- `@AGENTS.md` dentro do `CLAUDE.md` **não foi alterado**: é mudança nas regras do projeto e fica para decisão de Arthur (hoje o `AGENTS.md` não é carregado automaticamente).
- Auditoria independente do Codex: **pendente**; a prevista após a F1.4 e antes da escrita da F1.6 depende de execução na máquina de Arthur.
- Páginas oficiais de subagentes e skills foram lidas só até ~100 mil de ~110 mil caracteres (limite herdado da GH-F1.3).
