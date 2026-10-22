# Registro de decisões arquiteturais (ADR simplificado)

## ADR-001 — Toolkit independente
**Status:** adotada. Código e política reutilizáveis não dependem do Solenne ou de qualquer produto individual. Personalizações ficam em adaptadores opcionais.

## ADR-002 — Repositório público e segredos
**Status:** adotada. Somente definições, exemplos sanitizados, testes e documentação públicos. Credenciais, dados pessoais, memórias privadas do agente pessoal e logs sensíveis permanecem fora do Git.

## ADR-003 — Claude implementa; Codex audita
**Status:** adotada como fluxo desejado. Claude Code realiza implementações em escopo autorizado. Codex revisa de forma independente e read-only por padrão. Humano aprova integração.

## ADR-004 — Concorrência com ownership
**Status:** adotada. Agentes paralelos não compartilham propriedade de arquivos durante escrita. Worktrees separadas e coordenação pelo líder são mandatórias quando houver mudanças simultâneas.

## ADR-005 — Ativação progressiva
**Status:** adotada. Iniciar com agentes de leitura, depois escrita controlada, depois MCP e integrações. Hermes com controle do computador, automações de contas e WhatsApp exigem aprovação específica.

## Pendências
- Linguagem e runtime preferidos para ferramentas próprias.
- Formato do contrato de tarefas e mecanismo de armazenamento do catálogo.
- Política de custos e seleção de modelos.
- Importação e validação dos dois documentos completos de origem.
- Estratégia de publicação do toolkit em outros repositórios sem copiar credenciais.
