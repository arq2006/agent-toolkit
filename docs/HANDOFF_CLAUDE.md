# Primeira tarefa para Claude Code — F0 (documentação e contratos)

Este arquivo é o roteiro inicial. Não tente implementar todo o ecossistema em um único PR.

## Objetivo
Preparar o Agent Toolkit para desenvolvimento seguro e reutilizável: importar as fontes completas, validar as regras do repositório público e desenhar os primeiros contratos de agentes/skills. **Não** instalar Hermes, FreeLLMAPI, ElevenLabs, servidores MCP ou ativar Agent Teams nesta fase.

## Instruções para a primeira sessão
1. Abra o checkout de `arq2006/agent-toolkit` em Claude Code.
2. Leia README.md, CLAUDE.md, AGENTS.md, docs/ROADMAP_IMPLEMENTACAO.md, docs/DECISOES.md e docs/FONTES_E_IMPORTACAO.md.
3. Confirme `git status`, branch, HEAD e arquivos locais; preserve todo trabalho que não seja seu.
4. Faça AUDIT 0 estritamente read-only da estrutura, segurança de publicação e documentação disponível.
5. Localize os dois documentos completos já fornecidos pelo usuário, conforme FONTES_E_IMPORTACAO.md. Se ausentes, **não os invente**.
6. Entregue um plano pequeno de mudança para F0.1: importação íntegra dos documentos, índices e política de contribuição. Não iniciar escrita até o usuário aprovar escopo.
7. Depois da aprovação, crie branch `docs/import-source-plans` a partir da base confirmada, copie os arquivos verificados, execute a validação e abra PR em rascunho. Nunca faça merge.
8. Para F1, proponha apenas 3 agentes iniciais e suas permissões; espere uma tarefa própria.

## Critérios de aceite F0.1
- PDF e roadmap geral completos no Git sem alteração silenciosa.
- Ausência de segredos ou dados pessoais indevidos.
- Checksums registrados e documentação com links internos funcionais.
- Mudanças restritas a documentação/índices; sem serviços externos, hooks ativos ou mudanças de máquinas.
- PR com evidências de verificação e ressalvas claras.

## Entrega que quero ver
Um resumo com: branch e HEAD, arquivos identificados, riscos públicos, arquivos alterados, testes/checks, pendências, comandos executados e URL do PR. Se não encontrou documentos, reportar bloqueio e indicar os caminhos esperados sem improvisar conteúdo.
