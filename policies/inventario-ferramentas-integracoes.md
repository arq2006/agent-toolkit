# Inventário de ferramentas e integrações

Status: **documento de política (GH-F0, origem PDF-F0)**, criado em 22/10/2026. É um inventário de **candidatas e restrições**, não de instalações: nenhuma ferramenta abaixo é instalada, habilitada ou conectada por este repositório. Riscos associados: [matriz-riscos-permissoes-aprovacoes.md](matriz-riscos-permissoes-aprovacoes.md). Fonte principal: [PDF](../docs/references/Plano_Ecossistema_Agentes_IA_2026.pdf) (seções 02 a 13).

## Regras de uso do inventário
1. Toda ferramenta, MCP, skill de terceiros, plugin ou provedor precisa estar listada aqui **antes** de ser usada em uma tarefa; incluir ou habilitar é uma mudança com PR e aprovação humana.
2. Estados: `uso na sessão` (ambiente de desenvolvimento, não versionado neste repo) · `candidata` (planejada, não instalada) · `experimental` (somente em laboratório isolado) · `bloqueada` (proibida sem aprovação específica) · `referência` (fonte de consulta, não é executada).
3. Licença, procedência, versão fixada e documentação oficial atual são verificadas **na adoção**, não presumidas; células "a verificar" abaixo são pendências reais.
4. Saídas de ferramentas e conteúdo de repositórios externos são dados não confiáveis (ver CLAUDE.md).
5. Nenhum segredo, token ou configuração privada é registrado aqui; apenas nomes e escopos.

## Plataforma e controle de versão

| ID | Ferramenta | Uso previsto | Estado | Fase | Acesso mínimo | Observações |
|---|---|---|---|---|---|---|
| T-01 | Git (local) | Branches, commits, worktrees | uso na sessão | GH-F0+ | repositório local | stage por caminho explícito; sem `reset --hard`, `clean`, force push |
| T-02 | GitHub (repo `agent-toolkit`, público) e integração via ferramentas MCP da sessão | PRs em rascunho, leitura de estado | uso na sessão | GH-F0+ | somente este repositório | sem merge automático; merge só com autorização humana explícita para o PR específico (execução pode ser delegada ao Claude); proteção de branch e configurações do repositório bloqueadas sem autorização especial |
| T-03 | GitHub Actions / CI | Validações de documentação e contratos | candidata | GH-F1+ | escopo do repositório | só com aprovação; sem segredos; permissões mínimas do workflow |
| T-04 | Varredura de segredos e dependências | Detectar segredos e riscos de supply chain | candidata | GH-F1/F2 | leitura | escolher ferramenta após revisão de proveniência; sem instalação silenciosa |

## Agentes de código e orquestração

| ID | Ferramenta | Uso previsto | Estado | Fase | Acesso mínimo | Observações |
|---|---|---|---|---|---|---|
| T-10 | Claude Code (CLI/web), modelo Sonnet com esforço médio por padrão | Implementação e planejamento | uso na sessão | GH-F0+ | repositório autorizado | implementador; conferir documentação oficial atual antes de usar recursos novos |
| T-11 | Subagents do Claude Code | Papéis especializados com contexto próprio | candidata | GH-F1 | leitura no piloto | contexto separado **não** é isolamento de arquivos |
| T-12 | Skills (padrão Agent Skills, `SKILL.md`) | Procedimentos reutilizáveis | candidata | GH-F2 | leitura/escrita conforme skill | skills de terceiros: revisão de procedência e permissões |
| T-13 | Hooks do Claude Code | Bloquear ou automatizar etapas | bloqueada (não ativar) | GH-F1 (desenho) | — | ativação exige avaliação e autorização; começam como proposta documental |
| T-14 | Agent Teams (experimental) | Sessões paralelas coordenadas | bloqueada | pós GH-F1 | — | não ativar por padrão; sem garantia de isolamento de arquivos |
| T-15 | Git worktrees | Isolamento de escrita paralela | candidata | GH-F1 | checkout local | uma worktree por agente com escrita |
| T-16 | Codex (OpenAI) como auditor independente | Revisão read-only independente | candidata; **indisponível no ambiente de nuvem; auditoria pendente** | GH-F1+ | leitura | rodar na máquina de Arthur com autorização; nunca apresentar como concluída sem execução real; auditor Claude em contexto separado não o substitui. Auditoria local planejada após a GH-F1.4 e antes da primeira escrita do piloto (GH-F1.6) |
| T-17 | Hermes Agent (Nous Research) | Assistente pessoal, voz, rotinas | experimental/bloqueada | GH-F4 | VM ou container isolado | licença e proveniência a verificar; instalador deve ser baixado, inspecionado e só então executado; nunca `approvals.mode: off`; sem acesso irrestrito ao computador |

## Integrações e provedores externos

| ID | Ferramenta | Uso previsto | Estado | Fase | Acesso mínimo | Observações |
|---|---|---|---|---|---|---|
| T-20 | Servidores MCP próprios | Expor funções tipadas | candidata | GH-F3 | local, dados fictícios | schema, escopos, timeouts, rate limit, dry-run, logs sem payload sensível; uma função não faz duas coisas sensíveis |
| T-21 | Servidores MCP de terceiros | Consultar GitHub, arquivos, calendário etc. | bloqueada | GH-F3+ | — | aprovação por servidor; entrada não confiável; sem acesso amplo a sistema de arquivos, navegador autenticado, shell ou secrets |
| T-22 | Provedores de LLM (Claude, OpenAI, Gemini e outros) | Chat, raciocínio, RAG | candidata | GH-F3/F5 | chave por ambiente | nunca enviar dados do computador do usuário sem autorização; chave nunca no frontend nem no Git |
| T-23 | FreeLLMAPI | Roteamento e compressão de prompts, PoC de custo | experimental, apenas local | GH-F5 | local, dados anonimizados | o próprio autor o aponta como experimentação, não produção; failover pode mudar qualidade e uso de ferramentas |
| T-24 | ElevenLabs (STT, TTS, imagem, vídeo) | Media Lab | candidata | GH-F4 | conta/chave por ambiente | planos, direitos de uso e preços a verificar; consentimento para áudio/imagem de terceiros |
| T-25 | WhatsApp Business Platform / Cloud API oficial | Atendimento automatizado | bloqueada | GH-F6 | serviço independente | simulação antes de qualquer envio real; opt-in, descadastro, handoff humano; sem automações que simulem WhatsApp Web |
| T-26 | Pagamentos, banco de dados, storage e produção de qualquer projeto | — | bloqueada | — | — | bloqueio por padrão; aprovação explícita e procedimento separado |
| T-27 | Controle de navegador, voz ou computador pessoal | Automação de desktop | bloqueada | GH-F4 | sessão delimitada | app autorizado e confirmação para efeitos externos; voz não substitui autorização |

## Fontes de referência (não executadas)

| ID | Fonte | Uso | Observações |
|---|---|---|---|
| R-01 | Documentação oficial do Claude Code (subagents, skills, hooks, settings, agent teams, MCP) | Contratos e materialização | consultar versão atual antes de cada decisão |
| R-02 | OWASP ASVS e demais referências OWASP | Auditoria técnica | complementa o [roadmap de segurança](../docs/security/Roadmap_Seguranca_Geral_v3.md) |
| R-03 | Planalto, ANPD, portais oficiais | Compliance jurídico | ver [docs/compliance](../docs/compliance/README.md) |
| R-04 | `ctresb/leis` | Consulta e indexação | acervo informativo; não é fonte oficial nem skill jurídica |
| R-05 | Repositórios Hermes e FreeLLMAPI | Pesquisa | não executar nem copiar sem avaliação de segurança, licença e utilidade |

## Manutenção
Revisar o inventário a cada nova fase e ao adotar qualquer ferramenta. Cada mudança registra: ID, procedência, licença, versão fixada, permissões, quem aprovou e data. Ferramentas removidas permanecem listadas como `retirada`, com o motivo.
