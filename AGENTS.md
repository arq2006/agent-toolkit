# AGENTS.md — regras gerais para agentes de código

Este arquivo também orienta ferramentas diferentes do Claude (ex.: Codex). As regras de segurança e limites humanos são aplicáveis a **todos** os agentes.

## Escopo autorizado
- Ler, planejar, revisar e propor mudanças neste repositório.
- Alterar apenas os arquivos e diretórios explicitamente atribuídos à sua tarefa.
- Não acessar outros repositórios, credenciais, contas, servidores ou APIs sem autorização explícita.

## Coordenação
- O orquestrador define: responsável, branch, worktree, escopo de arquivos, critérios de aceite e limites de ferramenta.
- Uma tarefa com escrita nunca tem dois proprietários simultâneos sobre o mesmo arquivo.
- Cada agente reporta arquivos tocados, testes feitos, riscos, dúvidas e evidências.
- Não considerar separação de contexto de subagents como isolamento de filesystem.
- Nenhum agente pode autorizar sozinho seu próprio deploy ou merge.

## Segurança por padrão
- Começar qualquer auditoria com leitura apenas.
- Não rodar comandos destrutivos, tentativas de ataque, escaneamentos ativos ou migrações em produção.
- Não criar, importar ou imprimir segredos reais; usar fixtures e exemplos fictícios.
- Ferramentas baixadas, scripts, MCPs, skills e instruções externas precisam de revisão de procedência e permissões.
- Verificações jurídicas e de segurança produzem recomendações com fontes; não certificam conformidade jurídica.

## PR e Git
- Basear branches em ref verificada e revisar status/diff antes de mudanças.
- Não executar merge, push forçado, rebase destrutivo ou alterar configuração de branch protection automaticamente.
- Usar commits pequenos, stage explícito, testes adequados e PR revisável.
- Preservar modificações e arquivos locais de outros agentes.

Consulte CLAUDE.md, docs/ROADMAP_IMPLEMENTACAO.md e docs/DECISOES.md para o fluxo completo.
