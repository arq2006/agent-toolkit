# GH-F1.5 — Piloto somente leitura (planner + auditor)

Status: **preparado; NÃO executado.** O sandbox `/home/agent-pilot/agent-toolkit-sandbox` (conta Linux dedicada `agent-pilot`, decisão de Arthur em 22/10/2026) fica na máquina dele e **não foi criado**: a conta ainda não existe e a sessão de nuvem não tem acesso à máquina. O piloto **não** pode ser feito em outro lugar. Condições: [sandbox-gh-f1.md](../plans/sandbox-gh-f1.md); materialização: [materializacao-claude-code.md](../materializacao-claude-code.md).

Roteiros de ambiente isolado por sistema (propostas, não executadas): [Arch Linux](../setup/arch-linux.md), [Windows](../setup/windows.md) e [compatibilidade](../setup/compatibilidade-multiplataforma.md). O sandbox Linux na home da conta dedicada foi **aprovado por Arthur** (caminhos em [arch-linux.md](../setup/arch-linux.md) §2); o conteúdo fictício está em [examples/sandbox-fixture/](../../examples/sandbox-fixture/).

## Pré-requisitos (todos obrigatórios)
1. Conta `agent-pilot` criada por Arthur e testes de acesso (passo 3 do guia Arch) aprovados; **a execução é feita por Arthur no notebook**, sem Remote Control nesta rodada.
2. Verificar que `/home/agent-pilot/agent-toolkit-sandbox` **não existe ou está vazio**; se tiver qualquer arquivo, parar e relatar.
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
