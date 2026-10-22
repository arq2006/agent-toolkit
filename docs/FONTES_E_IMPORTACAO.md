# Fontes de referência e importação

## Estado verificado em 22/10/2026
Este repositório público tinha apenas um README na main quando o bootstrap começou. Portanto, **não afirmar que os documentos completos já estão no GitHub**.

## Fontes já preparadas fora deste repositório
1. `Plano_Ecossistema_Agentes_IA_2026.pdf` — estudo e planejamento de 17 páginas, preparado anteriormente.
2. `Roadmap_Seguranca_Geral_v3.md` — base geral reutilizável, com as etapas SEC-00 a SEC-42; substitui a personalização exclusiva do Solenne para novos projetos.
3. `Roadmap_Seguranca.md` — origem específica do Solenne; não copiar como política geral sem adaptação.

O usuário informou que o plano está em sua pasta local `docs/`. Os caminhos exatos precisam ser **descobertos no checkout local**, sem presumir que os documentos foram publicados nesta branch.

## Tarefa F0.1 para Claude Code
- Procurar no diretório de trabalho e em `docs/` os dois documentos completos. Não vasculhar diretórios pessoais externos ao projeto sem permissão.
- Conferir se os arquivos encontrados correspondem aos documentos desejados; se não estiverem disponíveis, solicitar ao usuário que os copie manualmente para `docs/references/`.
- Checar segredos, dados pessoais e caminhos locais antes de publicar em repo público.
- Importar preservando conteúdo: PDF como `docs/references/Plano_Ecossistema_Agentes_IA_2026.pdf` e Markdown como `docs/security/Roadmap_Seguranca_Geral_v3.md`.
- Criar checksums SHA-256 e registrar no PR. Não reescrever o texto original silenciosamente.
- Conservar o roadmap Solenne fora do toolkit, salvo aprovação específica para referência histórica.
- Não interpretar o resumo deste repositório como substituto do PDF e do Markdown completos.

## Fontes públicas de pesquisa
- Claude Code: https://code.claude.com/docs/en/
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- Corpus legal brasileiro: https://github.com/ctresb/leis — acervo informativo, NÃO é skill jurídica pronta nem fonte oficial definitiva.
- FreeLLMAPI: https://github.com/tashfeenahmed/freellmapi — para testes locais; documentação desaconselha uso em produção.
- OWASP: https://owasp.org/
- ANPD: https://www.gov.br/anpd/pt-br

Nenhum repositório externo será executado, instalado ou copiado integralmente sem avaliação de segurança, licença e utilidade.
