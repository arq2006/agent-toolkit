# ADR-010 — Materialização das definições em `.claude/`

**Status:** aceita (proposta na GH-F1.3; revisada por Arthur e integrada no PR #7, 22/10/2026). A aplicação inicial está em [materializacao-claude-code.md](../materializacao-claude-code.md) (GH-F1.4).

## Contexto
A [ADR-007](ADR-007-arquitetura-de-diretorios.md) definiu a fonte neutra em `agents/` e `skills/` e deixou aberto o mecanismo de materialização em `.claude/`. A [pesquisa](../pesquisas/claude-code-materializacao-2026-10-22.md) mostra que o Claude Code exige `name` e `description` no arquivo de agente, ignora campos desconhecidos, lê skills por symlink de diretório e trata CLAUDE.md como contexto, não como controle imposto.

## Decisão proposta
1. **Agentes:** gerar `.claude/agents/<nome>.md` a partir de `agents/<nome>/AGENT.md` por um procedimento de tradução com *dry-run* (mostra o diff antes de gravar) e revisão humana (A2). Mapeamento mínimo: `name`; `description` (derivada de `purpose` e de "quando usar", escrita à parte no `AGENT.md`); `tools`/`disallowedTools` a partir de `allowed_actions`/`forbidden_actions`; `model: sonnet` e `effort: medium`; corpo = instruções em prosa. Não copiar à mão.
2. **Skills:** preferir symlink de diretório `.claude/skills/<nome>` → `skills/<nome>` (confirmar com a versão instalada); `contract.yaml` fica ao lado e não é lido pelo Claude Code.
3. **Somente leitura por remoção de ferramentas:** `planner` e `auditor` recebem `tools` restritas (sem `Write`/`Edit`; `Bash` somente com necessidade comprovada e regras de permissão específicas) e `disallowedTools: Write, Edit`. O `permissionMode` não é confiável como único controle (é herdado se a sessão principal estiver em `bypassPermissions`, `acceptEdits` ou `auto`).
4. **Isolamento do implementador:** worktree (`isolation: worktree` ou worktree manual), reserva de arquivos e regras `deny` para caminhos protegidos (`docs/references/`, `docs/security/`, `docs/CHECKSUMS.sha256`); sandbox e hooks só após avaliação e aprovação próprias.
5. **Instruções:** avaliar `@AGENTS.md` dentro do `CLAUDE.md` (hoje o `AGENTS.md` não é carregado automaticamente porque existe `CLAUDE.md`).
6. **Agent Teams** permanecem desligados; **MCP e hooks** não são introduzidos na materialização inicial.
7. **Estado Git sem Bash (requisito da GH-F1.4):** agentes sem `Bash` (por exemplo `planner` e `auditor` restritos a `Read`, `Grep`, `Glob`) devem receber o **estado Git inicial e final** (HEAD, branch, `git status`, diff) por um **mecanismo seguro de preflight**, executado fora do agente (pelo Claude principal ou pelo humano) e entregue como dado, **sem conceder ao agente permissões adicionais de escrita** nem `Bash` amplo. O mecanismo exato é decidido e testado na GH-F1.4.
8. **Verificação de carregamento** (GH-F1.4): conferir a versão instalada e comprovar na prática que cada agente carrega, que o read-only recusa escrita e que as permissões efetivas são as esperadas; prompts sozinhos não comprovam isolamento.

## Alternativas
- Fonte direta em `.claude/agents/`: simples, mas acopla à ferramenta (rejeitada na ADR-007; reavaliar só se a tradução se mostrar custosa).
- Plugin versionado: viável, porém subagentes de plugin ignoram `hooks`, `mcpServers` e `permissionMode`; adiar.
- Symlink de arquivo para agentes: não confirmado na documentação consultada.

## Consequências
- Exige definir o campo `description` e a tabela de tradução na GH-F1.4 (ou antes, em ajuste do contrato de agente).
- Risco de deriva fonte × `.claude/` (RK-15): mitigado por geração e teste de contrato.
- Pendências: versão do Claude Code instalada, comportamento exato de `isolation: worktree` e de symlinks, esquema formal.
