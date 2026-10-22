# Pesquisa: materialização, subagentes, permissões e isolamento no Claude Code

Status: **pesquisa documental da GH-F1.3** (22/10/2026). Nada foi instalado, configurado ou executado; não existe `.claude/` neste repositório. Alimenta a [ADR-010](../adr/ADR-010-materializacao-em-claude-code.md) (proposta) e o [estudo da GH-F1.7](../plans/GH-F1-7-orquestracao-hierarquica.md).

## Método e limites
- Fonte: documentação oficial em `code.claude.com/docs/en/` ([sub-agents](https://code.claude.com/docs/en/sub-agents), [skills](https://code.claude.com/docs/en/skills), [settings](https://code.claude.com/docs/en/settings), [permissions](https://code.claude.com/docs/en/permissions), [memory](https://code.claude.com/docs/en/memory), [agent-teams](https://code.claude.com/docs/en/agent-teams)) e [agentskills.io/specification](https://agentskills.io/specification), lidas em 22/10/2026 por ferramenta de leitura de páginas.
- As páginas de `sub-agents` e `skills` foram lidas até cerca de 100 mil caracteres de 110 mil; os trechos finais (por exemplo parte de *fork* e *background*) **não foram lidos**. Os resumos podem ter perdido detalhes; confirmar o ponto exato antes de implementar.
- A versão do Claude Code instalada **não foi verificada**; vários recursos citam versões mínimas (por exemplo v2.1.x). Conferir na GH-F1.4 com a versão real.
- A documentação muda com frequência; datar e reverificar a cada decisão.

## 1. Subagentes: onde ficam e formato
- Locais, por prioridade: configurações gerenciadas, `--agents` (JSON, sessão), **`.claude/agents/`** (projeto), `~/.claude/agents/` (usuário), `agents/` de plugin. Edições em `.claude/agents/` são detectadas em segundos.
- Formato: arquivo Markdown com cabeçalho YAML; o corpo é o *system prompt*. **Obrigatórios: `name` e `description`.** Campos desconhecidos são ignorados em silêncio. Outros campos: `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`, `background`, `omitClaudeMd`, `effort`, `isolation` (`worktree`), `color`, `initialPrompt`, `experimental`.
- Implicação: o `AGENT.md` do toolkit **não é carregável como está**: não tem `description`, e `allowed_actions`, `file_scope` etc. não têm correspondência direta. É preciso uma **tradução** (ver ADR-010).
- A documentação consultada não menciona symlink para arquivos de agente (diferente de skills); tratar como não confirmado.

## 2. Skills
- Locais: `.claude/skills/<nome>/SKILL.md` (projeto), `~/.claude/skills/` (pessoal), enterprise, plugin, aninhados. **Uma entrada `<nome>` pode ser symlink para um diretório**; o `SKILL.md` é lido do destino.
- Claude Code segue o padrão Agent Skills e aceita campos extras (`when_to_use`, `disable-model-invocation`, `allowed-tools`, `context`, `agent`, `hooks`, `metadata` etc.). `metadata` é mapa livre **ignorado** pelo Claude Code. Fora do Claude Code (uploads, Skills API) só valem `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`; outro campo causa erro.
- **`allowed-tools` pré-aprova ferramentas no turno da skill e não restringe** o conjunto disponível; não é controle de permissão mínima. Consistente com a decisão do toolkit de não usá-lo (contrato de skill).
- Nosso `contract.yaml` ao lado do `SKILL.md` é compatível (arquivos adicionais são permitidos), mas o Claude Code não o lê: a permissão real vem das regras do Claude Code, não do contrato.

## 3. Subagentes aninhados e delegação
- Padrão: **até três camadas** abaixo da conversa principal; `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` ajusta (valor `1` desliga). Ao atingir o limite, a ferramenta `Agent` é retirada do subagente.
- Para impedir aninhamento num subagente: omitir `Agent` de `tools` ou listá-la em `disallowedTools`. A lista tipada `Agent(worker, researcher)` só vale para agente que roda como *thread* principal (`claude --agent`); dentro de definição de subagente é ignorada.
- Delegação: automática pela `description`, por pedido em linguagem natural ou por @-menção; sessão inteira com `claude --agent <nome>` ou `"agent"` em `.claude/settings.json`. Orçamento: aviso se as descrições somarem mais de ~15 mil tokens.
- Um subagente **não vê o histórico** da conversa: regras que devem chegar a ele precisam estar no prompt de delegação.
- Mensagens entre agentes **não concedem aprovação** nem alteram permissões ou configuração.

## 4. Permissões e isolamento
- Regras avaliadas na ordem **deny → ask → allow**, primeiro que casa decide; allow não abre exceção em deny. `Read` deny também bloqueia Edit/Write no mesmo caminho; regras de caminho valem só para `Edit(...)`/`Read(...)`.
- Modos: `default`, `acceptEdits`, `plan`, `dontAsk` (nega automaticamente o que pediria confirmação), `auto`, `bypassPermissions`. **Se a conversa principal está em `bypassPermissions`, `acceptEdits` ou `auto`, o subagente herda o modo e o `permissionMode` dele é ignorado.** Subagentes de plugin ignoram `hooks`, `mcpServers` e `permissionMode`.
- **Somente leitura de verdade** se obtém **removendo ferramentas** (`tools: Read, Grep, Glob` ou `disallowedTools: Write, Edit`), não por instrução em prompt. `Bash` permite escrita por comandos; regras de prefixo em Bash têm limites conhecidos (formas alternativas do mesmo programa, `sh -c`). Para isolamento de sistema de arquivos e rede independente do texto do comando, a documentação indica **sandbox** e *hooks* `PreToolUse`; ambos exigem avaliação e aprovação aqui.
- `isolation: worktree` roda o subagente numa worktree temporária e o Claude Code **bloqueia** comandos que apontem para o checkout principal; é removida se nada mudar. Branch de origem: a padrão do repositório (conferir o comportamento exato na GH-F1.4).
- `allowed-tools`/regras de projeto: regras `allow` de configuração do projeto só valem após confiança na pasta (*workspace trust*); `deny` e `ask` valem imediatamente. Chaves `bypassPermissions`/`auto` em `permissions.defaultMode` não valem vindas de configuração de projeto.
- Configurações: escopos gerenciado, `--settings`, local (`.claude/settings.local.json`), projeto (`.claude/settings.json`), usuário; listas (como `permissions.allow`) são mescladas entre arquivos.

## 5. Modelo e esforço
- Subagente: `model` aceita `sonnet`, `opus`, `haiku`, `fable`, ID completo ou `inherit`; `effort` aceita `low`, `medium`, `high`, `xhigh`, `max`. A variável `CLAUDE_CODE_EFFORT_LEVEL` tem precedência sobre o campo; `CLAUDE_CODE_SUBAGENT_MODEL` (+ `..._FORCE`) pode impor um único modelo.
- Compatível com a política do toolkit (Sonnet, esforço médio, elevação por tarefa); a elevação por tarefa precisa ser passada na delegação, pois o campo fixo do arquivo é o padrão.

## 6. Instruções do projeto: CLAUDE.md × AGENTS.md
- O Claude Code lê `AGENTS.md` **somente quando não há `CLAUDE.md`** no diretório de trabalho ou acima; havendo `CLAUDE.md`, lê só ele, a menos que o `CLAUDE.md` **importe** `AGENTS.md` (sintaxe `@AGENTS.md`) ou a configuração de instruções do projeto seja alterada.
- **Achado:** este repositório tem `CLAUDE.md` que **não** importa `AGENTS.md`; logo, o Claude Code carrega o `CLAUDE.md` mas não o `AGENTS.md` automaticamente (o `CLAUDE.md` manda ler, o que depende de o agente seguir a instrução). Recomendação para a GH-F1.4: avaliar `@AGENTS.md` no `CLAUDE.md`, sem duplicar regras.
- A própria documentação diz que CLAUDE.md e memória são **contexto, não configuração imposta**; para bloquear uma ação use regras de permissão, sandbox ou hooks.

## 7. Agent Teams
- **Experimentais e desligados por padrão** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Custo de tokens bem maior; limitações: sem retomada de sessão com teammates in-process, **sem equipes aninhadas**, uma equipe por sessão, tarefas podem ficar com status defasado.
- Com a variável ativa, **subagentes nomeados pelo Claude passam a iniciar como teammates**, ou seja, equipes podem se formar sem pedido explícito. Manter desligado (`0`) é parte do requisito de não ativar Agent Teams.
- Dois teammates editando o mesmo arquivo causam sobrescrita: a reserva exclusiva de arquivos do contrato de tarefa continua necessária.

## Síntese para as decisões
1. Materialização de **agentes** exige gerar `.claude/agents/<nome>.md` a partir de `agents/<nome>/AGENT.md` (tradução + `description`), com *dry-run* e revisão humana; copiar à mão duplica a fonte.
2. Materialização de **skills** pode usar **symlink de diretório** (`.claude/skills/<nome>` → `skills/<nome>`), confirmando o comportamento com a versão instalada.
3. Isolamento de escrita deve vir de **remoção de ferramentas, regras deny, worktree e (se aprovado) sandbox**, nunca só de instruções.
4. Importar `AGENTS.md` no `CLAUDE.md` evita que regras comuns a outras ferramentas sejam perdidas.
5. Hooks, sandbox, Agent Teams e MCP continuam **bloqueados** até avaliação e autorização próprias.
