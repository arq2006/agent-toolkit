# GH-F1.5 — Piloto somente leitura (planner + auditor)

Status: **piloto executado parcialmente; aceite integral pendente.** Arthur executou parte do roteiro no notebook; as evidências históricas dessa execução **não foram anexadas a este PR nem lidas por esta sessão** e devem ser preservadas como estão. O aceite integral depende de repetir os passos corrigidos (2b, 7b, 8 e 9 do [guia Arch](../setup/arch-linux.md)) e de um manifesto de evidências completo. Condições: [sandbox-gh-f1.md](../plans/sandbox-gh-f1.md); materialização: [materializacao-claude-code.md](../materializacao-claude-code.md).

Roteiros de ambiente isolado por sistema (esta sessão não executou nada na máquina de Arthur): [Arch Linux](../setup/arch-linux.md), [Windows](../setup/windows.md) e [compatibilidade](../setup/compatibilidade-multiplataforma.md). O sandbox Linux na home da conta dedicada foi **aprovado por Arthur** (caminhos em [arch-linux.md](../setup/arch-linux.md) §2); o conteúdo fictício está em [examples/sandbox-fixture/](../../examples/sandbox-fixture/).

## Achados da auditoria Codex sobre o PR #9 e tratamento (nesta revisão)
| # | Sev. | Achado | Tratamento |
|---|---|---|---|
| 1 | P1 | criação destrutiva do canário | passo 2 só lê; canário (2b) opcional, recusa caminhos/links existentes antes de escrever, sem `mkdir -p`/`chmod` em existentes, `noclobber` |
| 2 | P2 | ferramentas efetivas | passo 7b separa configuração, inventário do `init` do harness, tentativas e bloqueios observados; ausência de escrita ≠ bloqueio; teste de deny em tempo de execução segue pendente |
| 3 | P2 | evidências | passo 9: `manifest.json` com SHAs, versões, comandos/horários (`commands.log`), prompts (arquivos + hash) e hashes das saídas |
| 4 | P2 | limites dos snapshots | §9 do guia lista o que o snapshot não cobre; passo 8 acrescenta estado complementar e `find -newer`; sem alegar isolamento absoluto |
| 5 | P2 | planner e estado final | prompt avisa que só o estado inicial foi entregue; verificação automática do relato (`REVISAR`); ajuste de `AGENT.md` fica pendente de autorização |
| 6 | P2 | auditor sem SHAs/contrato | prompt inclui `BASE`/`HEAD`, resumo do diff e contrato concreto gerado em `pilot-evidence` (modelo da fixture com marcadores) |
| 7 | P3 | status documental | "piloto executado parcialmente; aceite integral pendente" em README, ROADMAP, HANDOFF, DECISOES e guias |

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
