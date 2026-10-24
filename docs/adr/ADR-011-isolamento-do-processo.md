# ADR-011 — Isolamento portátil do processo do agente

**Status:** proposta (GH-F1.8, provisório; 24/10/2026). Esta ADR registra **arquitetura proposta e evidências de um spike manual**. Nada aqui está implementado, e **nenhum ambiente é classificado como STRONG hoje**. O identificador GH-F1.8 é provisório e a numeração oficial será fixada na revisão. A GH-F1.5 (PR #9) permanece intacta e a GH-F1.6 continua bloqueada.

## Contexto
- O sandbox embutido do Claude Code cobre Bash/PowerShell e filhos; Read/Edit/Write, hooks, MCP locais e LSP rodam fora dele, e a leitura é ampla por padrão (pesquisa do projeto "modelos locais e isolamento", de 23/10/2026, que cita a documentação oficial; arquivo fora deste repositório).
- O `sandbox-runtime` (`srt`) é beta e isola o processo inteiro com bubblewrap (Linux/WSL2) ou Seatbelt (macOS).
- A GH-F1.5 produziu evidência pontual de bloqueio de leitura (inclusive `EACCES` em teste com a ferramenta Read do Claude Code) e uma barreira de home por conta dedicada ([plano do sandbox](../plans/sandbox-gh-f1.md)); **não** comprovou isolamento abrangente de leitura nem de rede. A evidência histórica da GH-F1.5 não é alterada por esta ADR.
- Requisito do produto: o usuário escolhe uma **pasta autorizada**; o toolkit verifica o isolamento automaticamente e **bloqueia operações inseguras**, sem usuários Linux adicionais nem configuração manual complexa.

## Evidências do spike (24/10/2026, Arch Linux, execução manual de Arthur)
Ambiente: bubblewrap 0.12.0, srt 0.0.81, Claude Code 2.1.302. Registro informado por Arthur; não há log versionado neste repositório.

**[PROVADO] nesse ambiente**
1. bubblewrap funciona sem sudo e sem usuário Linux adicional.
2. srt com `denyRead ["/"]` e exceções específicas: escrita permitida no workspace; leitura e escrita privadas bloqueadas.
3. Node.js e subprocessos respeitaram as restrições testadas.
4. `/proc` e conexões TCP externas e de loopback foram bloqueados.
5. Claude Code iniciou dentro do srt com home fictícia.
6. Claude Pro (autenticação claude.ai) funcionou como coordenador com `--restricted --tools ""`.
7. Cadeia coordenador → validador JSON estrito → executor no srt criou um marcador fictício.

**[LIMITAÇÃO CONFIRMADA]** hardlinks preexistentes podem permitir leitura de arquivo fora da pasta autorizada.

**[NÃO DEMONSTRADO]**
- Isolamento integral com Claude autenticado **dentro** da fronteira, e o escopo das credenciais nesse caso.
- Qualquer mitigação de hardlink, symlink e caminhos indiretos por código.
- Comportamento com agentes que usam Read/Edit nativos.
- Ollama, LM Studio, WSL2, macOS e Windows nativo.
- Estabilidade do srt entre versões e comportamento fail-closed por código.

## Decisão proposta
1. **Arquitetura portátil.** Isolamento do processo inteiro por srt sobre bubblewrap/Seatbelt. Sem usuários Linux adicionais, sem Docker obrigatório. O toolkit **não instala** srt nem bubblewrap; apenas detecta, verifica a versão fixada e orienta.
2. **Implementação futura** em `integrations/isolation/` ([ADR-007](ADR-007-arquitetura-de-diretorios.md)), Python 3.11+ somente com biblioteca padrão e configuração em TOML. Código fica para PRs posteriores com autorização específica.
3. **Configuração explícita:** pasta autorizada, autenticação (nenhuma ou coordenador claude.ai fora da fronteira) e rede (negada por padrão; allowlist explícita). Config ausente ou inválida recusa iniciar.
4. **Sem fallback silencioso.** Dependência ausente, versão diferente, config não carregada ou teste falho resulta em recusa. ADVISORY é um modo declarado sem acesso a arquivos, nunca uma degradação automática.
5. **Executor isolado.** Aceita apenas um conjunto fechado de operações em JSON estrito, validadas fora do sandbox e revalidadas dentro; nenhum campo vira comando de shell; nada de comando arbitrário produzido pela IA.
6. **Fail-closed para caminhos.** Recusar absolutos, `..`, NUL, qualquer symlink em componentes do caminho, arquivos não regulares, hardlinks (`st_nlink > 1`) e qualquer caminho cuja resolução saia da pasta autorizada. Abrir com `O_NOFOLLOW` e conferir `fstat` após abrir. Isto reduz, mas não elimina, TOCTOU e **não protege** processos que leem arquivos fora do executor.
   A verificação de hardlinks do executor JSON **não protege automaticamente** agentes com Read/Edit nativos, que não passam pelo executor. Para esses agentes, STRONG exige mitigação **comprovada para toda a árvore autorizada**; sem ela, operações com arquivos permanecem BLOCKED.
7. **Classificação do `toolkit doctor`** (a implementar):
   - **STRONG** exige validação efetiva, por testes reais executados no momento da verificação, de: isolamento de leitura e de escrita; subprocessos; caminhos indiretos (symlinks, `..`); hardlinks; rede; carga efetiva da config; e comportamento fail-closed. Ausência de credenciais e de rede, sozinha, **não** basta.
   - **ADVISORY** quando algum item não é comprovado mas o risco é aceitável em modo sem acesso a arquivos.
   - **BLOCKED** quando um item obrigatório falha ou não pode ser executado, ou quando o risco impede tarefas com arquivos.
   - Plataformas fora do spike (WSL2, macOS, Windows) valem no máximo ADVISORY até serem testadas; WSL2 é o primeiro alvo, Windows nativo não é MVP.
8. **Coordenador autenticado fora do sandbox** (arquitetura do spike) é uma arquitetura **distinta** do requisito de isolamento integral. Nela o processo autenticado tem acesso amplo e só a execução fica isolada; por isso não pode ser apresentada como isolamento integral nem classificada como STRONG. Se essa arquitetura for adotada, deve ser documentada como tal, com a fronteira explícita.
9. Credenciais nunca são expostas ao agente isolado; o toolkit não lê, copia nem versiona credenciais.

## Critérios pendentes para STRONG
Antes de qualquer declaração de STRONG: (a) implementação revisada e testes negativos por item do §7; (b) mitigação e teste de hardlinks e symlinks; (c) decisão e teste sobre onde roda o processo autenticado; (d) teste por plataforma; (e) fixação de versão do srt e canário de carga da config; (f) revisão humana e, quando disponível, auditoria independente do Codex (pendente).

## Alternativas
- Usuário Linux dedicado: rejeitada (configuração manual com sudo; limita fs mas não rede nem leitura além da home).
- Docker/container obrigatório: rejeitada como padrão; permanece alternativa para plataformas sem bubblewrap.
- Apenas o sandbox embutido do Claude Code: rejeitada (não cobre ferramentas de arquivo, hooks e MCP).

## Consequências e riscos
- srt é beta e pode mudar; versão fixada e verificação ativa são obrigatórias.
- Em Ubuntu 24.04+, restrições de user namespaces (AppArmor) podem impedir bubblewrap; o toolkit apenas reporta, sem alterar sysctl.
- Rede permitida a domínios amplos pode exfiltrar dados lidos.
- O modo de baixo risco da fase inicial é coordenador sem ferramentas (`--tools ""`) mais executor; agentes com escrita (GH-F1.6/`implementer`) continuam bloqueados.
- Auditoria independente do Codex segue **pendente**.

## Fora de escopo
Catálogo de 17 agentes, GH-F1.6/`implementer`, modelos locais, hooks, MCP, qualquer alteração em evidências da GH-F1.5 ou em outros projetos.
