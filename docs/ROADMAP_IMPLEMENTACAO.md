# Roadmap de implementação — Agent Toolkit

Status: planejamento; etapas não iniciadas. Base: estudo prévio “Ecossistema pessoal de agentes de IA e automações”, de 22/10/2026. Documentos de origem importados na F0.1 (ver [README](README.md) e [ADR-006](adr/ADR-006-correspondencia-de-fases.md) para a correspondência com as fases F0–F7 do PDF).

## Sequência e critérios

### F0 — Fundamentação e publicação de documentos (AGORA)
- Conferir README, CLAUDE.md, AGENTS.md e política para repositório público.
- Importar sem perda os dois arquivos de referência: PDF do plano e Markdown completo de segurança.
- Verificar conteúdo, hash, atribuição e ausência de segredos/dados pessoais antes de publicar.
- Criar índice documental, decisões arquiteturais e tarefas de implementação.
**Aceite:** referências completas versionadas; nenhum arquivo privado publicado; revisão humana concluída.

### F1 — Agentes Claude Code
- Analisar a versão instalada e as capacidades oficiais de subagents, skills, hooks e teams.
- Criar poucos agentes iniciais: planner, implementer e reviewer, com descrições claras.
- Preferir subagents somente de leitura no piloto; não ativar Agent Teams experimental por padrão.
- Implementar contrato de tarefa: dono de arquivos, branch, worktree, critérios de aceite, resumo e evidências.
- Verificar carregamento real de agentes e skills por testes manuais/documentados.
**Aceite:** tarefas de leitura paralelas sem conflito; implementação isolada demonstrada em projeto descartável.

### F2 — Skills, guardrails e auditoria reutilizável
- Criar skills do padrão Agent Skills com SKILL.md e documentação auxiliar.
- Skills candidatas: preflight-git, security-audit-readonly, code-review, generate-skill, review-pr.
- Transformar o roadmap de segurança em checklists por projeto e matriz de aplicabilidade.
- Incluir controles contra prompt injection, exfiltração, execução sem consentimento e ferramentas não confiáveis.
- Testar casos negativos e conflitos de permissão.
**Aceite:** resultados repetíveis, logs não sensíveis e permissões comprovadas.

### F3 — Ferramentas próprias, MCP e adaptadores
- Definir interfaces para chamar ferramentas com schema, timeouts, escopos e dry-run.
- Criar um MVP local e isolado antes de conectar qualquer serviço externo.
- Adaptadores específicos por projeto devem viver em seus projetos, ou em módulos opcionais revisados.
**Aceite:** execução local de ponta a ponta com dados fictícios e sem credenciais reais no Git.

### F4 — Hermes e multimodalidade
- Verificar licença/proveniência do Hermes Agent e a documentação atual.
- Começar sem acesso ao computador, contas ou dados privados. Habilitar capacidades gradualmente com aprovações explícitas.
- Experimentar memória local, rotinas, transcrição, TTS e comandos de voz com opt-in.
- Avaliar APIs ElevenLabs e demais provedores por tarefa, custo, latência, consentimento e termos.
**Aceite:** parada de emergência, log auditável e nenhuma ação sensível sem aprovação.

### F5 — Economia de tokens e modelos
- Medir baseline de tokens, custo, tempo e qualidade com tarefas idênticas.
- Testar FreeLLMAPI apenas em PoC local: compressão off/lossless/standard; observar fidelidade e limites por provedor.
- Não confundir redução de tokens com redução de quotas do Claude Pro.
- Manter APIs pagas estáveis para qualquer produção que dependa de SLA.
**Aceite:** relatório reproduzível, com ganhos reais e regressões.

### F6 — Automação de atendimento e produtos
- Avaliar WhatsApp Business Platform oficial e exigências de consentimento, privacidade, opt-out e handoff humano.
- Iniciar com simulação de mensagens, sem envio real. Agendar implantação somente após análise jurídica e operacional.
**Aceite:** revisão de conformidade, salvaguardas comerciais e opção de atendimento humano.

## Regras transversais
- Pequenos PRs por fase. Sem implementação simultânea de etapas dependentes.
- Nenhuma funcionalidade executável deve ser considerada pronta sem teste e documentação.
- Um piloto de leitura vem antes de agentes que escrevem ou mexem no computador.
- Segurança e conformidade acompanham cada entrega; checklist não substitui revisão técnica e jurídica.
