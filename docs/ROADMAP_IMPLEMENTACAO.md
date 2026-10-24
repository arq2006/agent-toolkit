# Roadmap de implementação — Agent Toolkit

Status: planejamento; **GH-F0 a GH-F1.4 concluídas** (PRs #1 a #8 integrados na main); **GH-F1.5 (piloto somente leitura): piloto executado parcialmente; aceite integral pendente**; GH-F1.6 e GH-F2 a GH-F6 não iniciadas; GH-F1.7 é proposta futura não aprovada. Base: estudo prévio “Ecossistema pessoal de agentes de IA e automações”, de 22/10/2026. Documentos de origem importados na F0.1 (ver [README](README.md)). **Numeração:** as fases deste roadmap são **GH-F0 a GH-F6** (referência operacional); o PDF usa PDF-F0 a PDF-F7. Correspondência em [ADR-006](adr/ADR-006-correspondencia-de-fases.md). Plano da GH-F1: [plans/](plans/GH-F1-arquitetura-inicial-agentes.md).

## Sequência e critérios

### GH-F0 — Fundamentação e publicação de documentos (concluída) · origem: PDF-F0
- Conferir README, CLAUDE.md, AGENTS.md e política para repositório público.
- Importar sem perda os dois arquivos de referência: PDF do plano e Markdown completo de segurança.
- Verificar conteúdo, hash, atribuição e ausência de segredos/dados pessoais antes de publicar.
- Criar índice documental, decisões arquiteturais e tarefas de implementação.
- F0.2: padronizar fases ([ADR-006](adr/ADR-006-correspondencia-de-fases.md)), definir a arquitetura de diretórios ([ARQUITETURA.md](ARQUITETURA.md), [ADR-007](adr/ADR-007-arquitetura-de-diretorios.md)) e estruturar compliance ([ADR-008](adr/ADR-008-compliance-juridico-separado-do-tecnico.md)).
- Inventário de ferramentas e integrações ([policies/inventario-ferramentas-integracoes.md](../policies/inventario-ferramentas-integracoes.md)) e matriz de riscos, permissões e aprovações ([policies/matriz-riscos-permissoes-aprovacoes.md](../policies/matriz-riscos-permissoes-aprovacoes.md)): documentos criados e integrados.
**Aceite:** referências completas versionadas; nenhum arquivo privado publicado; revisão humana concluída.

### GH-F1 — Agentes Claude Code · origem: PDF-F1 e PDF-F2
- Analisar a versão instalada e as capacidades oficiais de subagents, skills, hooks e teams.
- Criar poucos agentes iniciais: planner, implementer e reviewer, com descrições claras.
- Preferir subagents somente de leitura no piloto; não ativar Agent Teams experimental por padrão.
- Implementar contrato de tarefa: dono de arquivos, branch, worktree, critérios de aceite, resumo e evidências.
- GH-F1.1: contratos de agente, skill e tarefa em [contratos/](contratos/README.md) (concluída).
- GH-F1.2: definições documentais dos três agentes em [../agents/](../agents/README.md) (concluída).
- GH-F1.3: pesquisa em [pesquisas/](pesquisas/claude-code-materializacao-2026-10-22.md) e [ADR-010](adr/ADR-010-materializacao-em-claude-code.md) (proposta); GH-F1.7 (futura): [plans/GH-F1-7-orquestracao-hierarquica.md](plans/GH-F1-7-orquestracao-hierarquica.md).
- GH-F1.8 (provisório; proposta, documental): [ADR-011](adr/ADR-011-isolamento-do-processo.md), isolamento portátil do processo (srt/bubblewrap), `toolkit doctor` STRONG/ADVISORY/BLOCKED e executor de operações validadas, a implementar em `integrations/isolation/` só com autorização específica. Não substitui nem altera a GH-F1.5; a GH-F1.6 segue bloqueada.
- Reserva de arquivos, worktrees e relato de evidências por tarefa (PDF-F2).
- Desenhar e avaliar hooks (não ativar sem autorização) e simulação em repositório sandbox descartável (PDF-F1).
- Definir a materialização em `.claude/` a partir da fonte neutra ([ADR-007](adr/ADR-007-arquitetura-de-diretorios.md)).
- Verificar carregamento real de agentes e skills por testes manuais/documentados.
**Aceite:** tarefas de leitura paralelas sem conflito; implementação isolada demonstrada em projeto descartável.

### GH-F2 — Skills, guardrails, compliance e auditoria reutilizável · origem: PDF-F1 (skills) e PDF-F3
- Criar skills do padrão Agent Skills com SKILL.md e documentação auxiliar.
- Skills candidatas: preflight-git, security-audit-readonly, code-review, generate-skill, review-pr.
- Transformar o roadmap de segurança em checklists por projeto e matriz de aplicabilidade.
- Incluir controles contra prompt injection, exfiltração, execução sem consentimento e ferramentas não confiáveis.
- Testar casos negativos e conflitos de permissão.
- Trilha de **compliance jurídico**, separada da auditoria técnica de segurança: checklist de 17 itens, mapa de dados, fontes oficiais e relatório por projeto, conforme [compliance/](compliance/README.md). Skill candidata: `legal-web-check` (recomendação com fontes, não parecer jurídico).
**Aceite:** resultados repetíveis, logs não sensíveis e permissões comprovadas.

### GH-F3 — Ferramentas próprias, MCP e adaptadores · origem: PDF-F5
- Definir interfaces para chamar ferramentas com schema, timeouts, escopos e dry-run.
- Criar um MVP local e isolado antes de conectar qualquer serviço externo.
- Adaptadores específicos por projeto devem viver em seus projetos, ou em módulos opcionais revisados.
**Aceite:** execução local de ponta a ponta com dados fictícios e sem credenciais reais no Git.

### GH-F4 — Hermes e multimodalidade · origem: PDF-F4 e PDF-F5 (Media Lab)
- Verificar licença/proveniência do Hermes Agent e a documentação atual.
- Começar sem acesso ao computador, contas ou dados privados. Habilitar capacidades gradualmente com aprovações explícitas.
- Experimentar memória local, rotinas, transcrição, TTS e comandos de voz com opt-in.
- Avaliar APIs ElevenLabs e demais provedores por tarefa, custo, latência, consentimento e termos.
**Aceite:** parada de emergência, log auditável e nenhuma ação sensível sem aprovação.

### GH-F5 — Economia de tokens e modelos · origem: PDF-F6
- Medir baseline de tokens, custo, tempo e qualidade com tarefas idênticas.
- Testar FreeLLMAPI apenas em PoC local: compressão off/lossless/standard; observar fidelidade e limites por provedor.
- Não confundir redução de tokens com redução de quotas do Claude Pro.
- Manter APIs pagas estáveis para qualquer produção que dependa de SLA.
**Aceite:** relatório reproduzível, com ganhos reais e regressões.

### GH-F6 — Automação de atendimento e produtos · origem: PDF-F7
- Avaliar WhatsApp Business Platform oficial e exigências de consentimento, privacidade, opt-out e handoff humano.
- Iniciar com simulação de mensagens, sem envio real. Agendar implantação somente após análise jurídica e operacional.
**Aceite:** revisão de conformidade, salvaguardas comerciais e opção de atendimento humano.

## Regras transversais
- Pequenos PRs por fase. Sem implementação simultânea de etapas dependentes.
- Nenhuma funcionalidade executável deve ser considerada pronta sem teste e documentação.
- Um piloto de leitura vem antes de agentes que escrevem ou mexem no computador.
- Segurança e conformidade acompanham cada entrega; checklist não substitui revisão técnica e jurídica.
