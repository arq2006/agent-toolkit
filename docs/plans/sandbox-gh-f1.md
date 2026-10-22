# Sandbox descartável das etapas GH-F1.5 e GH-F1.6

Status: **condições aprovadas por Arthur em 22/10/2026; o sandbox NÃO foi criado.** Este documento registra as condições; ele não executa nada. Plano geral: [GH-F1-arquitetura-inicial-agentes.md](GH-F1-arquitetura-inicial-agentes.md). Políticas: [matriz](../../policies/matriz-riscos-permissoes-aprovacoes.md).

## Autorização (limitada)
Criação de um repositório Git **local e descartável** em `~/Projetos/agent-toolkit-sandbox`, **exclusivamente** para a GH-F1.5 e a GH-F1.6. Não vale para nenhuma outra etapa, caminho ou finalidade.

## Condições obrigatórias
1. **Antes de criar**, verificar que o caminho não existe ou está completamente vazio. Se contiver qualquer arquivo, interromper e relatar.
2. Nenhum repositório remoto no GitHub (nem push para qualquer remoto).
3. Somente dados e arquivos **fictícios**.
4. Não acessar nem modificar outros projetos (incluindo Solenne, FIINA e Velaris).
5. Não apagar o sandbox automaticamente; remoção só por decisão humana.
6. **GH-F1.5:** somente testes de leitura; nenhuma escrita no sandbox pelos agentes do piloto.
7. **GH-F1.6:** escrita exclusivamente no sandbox e em worktree isolada, **depois de nova verificação de segurança** (preflight do caminho, estado Git, permissões efetivas) e da auditoria local do Codex quando disponível (ou registro de que continua pendente).
8. **Verificar as permissões efetivas das ferramentas** antes de cada etapa: instruções em prompts, sozinhas, não comprovam isolamento de escrita. Registrar a evidência (por exemplo, tentativa controlada de escrita bloqueada para agente read-only).

## Observações
- O caminho fica na máquina de Arthur; a execução exige acesso à pasta aprovada no dispositivo, sujeito às permissões da ferramenta usada.
- Cada etapa apresenta evidências, testes, riscos e pendências antes de qualquer integração. A aprovação do sandbox não autoriza merge automático nem execução antecipada dos pilotos.
