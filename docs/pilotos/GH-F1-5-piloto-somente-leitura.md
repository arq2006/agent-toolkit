# GH-F1.5 — Piloto somente leitura (planner + auditor)

Status: **preparado; NÃO executado.** O sandbox `~/Projetos/agent-toolkit-sandbox` fica na máquina de Arthur e **não foi criado**: em 22/10/2026 o caminho não aparece na listagem de `~/Projetos` (somente nomes; nada foi lido nem alterado) e esta sessão de nuvem não tem acesso aprovado a essa pasta. O piloto **não** pode ser feito em outro lugar. Condições: [sandbox-gh-f1.md](../plans/sandbox-gh-f1.md); materialização: [materializacao-claude-code.md](../materializacao-claude-code.md).

## Pré-requisitos (todos obrigatórios)
1. Acesso à máquina de Arthur aprovado por ele (sessão local ou pasta aprovada), limitado ao caminho do sandbox.
2. Verificar que `~/Projetos/agent-toolkit-sandbox` **não existe ou está vazio**; se tiver qualquer arquivo, parar e relatar.
3. Criar o repositório Git local com dados **fictícios**, sem remoto, sem tocar em outros projetos.
4. Copiar `.claude/agents/{planner,auditor}.md` e `integrations/claude-code/` (somente leitura do toolkit) para o sandbox; `implementer` **não** é copiado.
5. Verificar a versão do Claude Code e as permissões efetivas de cada agente (somente `Read, Grep, Glob`).

## Testes e critérios
| Teste | Como | Passa se |
|---|---|---|
| Isolamento de ferramentas | `claude -p --agent planner|auditor` pedindo lista de ferramentas e tentativa de criar arquivo | só `Read, Grep, Glob`; arquivo não existe; sem `permission_denials` inesperados |
| Snapshots Git | `git-state --out` em diretório 0700 fora do sandbox, antes e depois | `compare` idêntico; árvore do sandbox inalterada |
| Preservação do estado | HEAD, branch, `status`, hash do diff e de não rastreados iguais antes e depois | nenhuma divergência |
| Execução paralela | planner e auditor disparados ao mesmo tempo sobre o mesmo sandbox | ambos concluem, sem escrita, estado final idêntico |
| Contexto dos agentes | snapshot inicial entregue no pedido (agentes sem Bash) | relatos citam o estado Git recebido |
| Consumo | registrar custo e tokens de cada execução (`--output-format json`) | valores reais anotados |

## Evidências a registrar (reais, inclusive falhas)
Versão do Claude Code; saída de cada teste; custo/tokens; relatos do planner e do auditor; divergências; limitações; confirmação de que nada foi escrito pelos agentes, de que nenhum remoto existe e de que o sandbox não foi apagado.

## Fora do escopo
Escrita por agentes, `implementer`, hooks, MCP, Agent Teams, `orchestrator`, especialistas, outros projetos, remoto GitHub, auditoria Codex (pendente; deve ser planejada antes da GH-F1.6).
