# GH-F1.8 / PR5 — Integração read-only sob SRT, somente dados fictícios

**Status: protótipo experimental, inativo, sem agentes.**

Esta etapa conecta de forma **limitada** `readonly_executor.py` à execução de um
processo Python controlado pelo SRT 0.0.81, em uma **fixture temporária nova**.
Não concede capacidade de ferramenta ao Claude, não acessa projetos reais,
não altera configurações de agentes, não roda `implementer`, não usa o sandbox
histórico e não faz merge automático.

## Evidências anteriores e motivação

- GH-F1.8/PR4 foi integrado à `main` como biblioteca inativa em `8c933575`.
  No Arch, **139 testes** passaram e a segunda revisão independente Codex
  não encontrou novos achados acionáveis no diff corrigido.
- O `toolkit_doctor` passou canários SRT básicos, mas reproduziu leitura
  externa via hardlink com acesso nativo. Portanto o SRT sozinho não basta.
- Documentação upstream SRT: `filesystem.allowWrite = []` desabilita
  permissões gerais de escrita, enquanto `denyRead = ["/"]` com `allowRead`
  restrito constitui a fronteira inicial de leitura.
  https://github.com/anthropics/sandbox-runtime
- Limitação relevante no SRT/Linux: o diretório interno `/tmp/claude`
  pode continuar compartilhado/gravável por padrão em determinadas versões,
  mesmo com política de escrita vazia. **Este piloto não reivindica isolamento
  entre sandboxes concorrentes.**
  https://github.com/anthropics/sandbox-runtime/issues/654

## Implementação proposta

Arquivo: `integrations/isolation/srt_readonly_pilot.py`:

1. Detecta `srt==0.0.81`, `node`, `bwrap`, `socat`, `rg` e
   `apply-seccomp`, reutilizando `srt_launcher.py`. Ausência, versão
   incompatível ou política inválida interrompe sem fallback.
2. Cria fixture 0700 descartável. Sob a pasta autorizada sintética, cria
   **nova subpasta** sem hardlinks ou symlinks, copia apenas os módulos
   versionados `pathguard.py` e `readonly_executor.py` e grava um marcador
   fictício. Nenhum outro workspace é montado ou lido.
3. Gera política SRT restritiva: `denyRead=["/"]`, `allowRead` para essa
   subpasta + dependências mínimas previamente justificadas,
   `allowWrite=[]`, `denyWrite=[]`, rede `deny`, seccomp ativo.
   Essa política NÃO substitui a política do `toolkit_doctor`.
4. Executa **somente** um script Python fixo com `-I -B -c`, importando as
   cópias fictícias dos módulos e realizando pedidos JSON predefinidos.
   Nenhum comando externo, prompt de IA, configuração pessoal ou caminho
   arbitrário é aceito como argumento da CLI.
5. Exige controle positivo de leitura/listagem, negativas para travessia
   de diretórios, caminho absoluto, requisição de escrita, leitura nativa
   externa e escrita nativa dentro da pasta autorizada.
6. Instala na fixture fictícia, APÓS o controle positivo, um hardlink para
   um marcador externo fictício. Uma segunda execução deve recusar tanto
   o hardlink quanto uma leitura normal enquanto a árvore é insegura.
   A leitura **nativa** do hardlink é relatada como LIMITAÇÃO informativa,
   nunca considerada prova de segurança.
7. Só retorna código 0 se **todos** os controles obrigatórios passarem.
   Ausência de evidência, bloqueio de runtime, timeout ou exceção resultam em
   código 2. Mesmo com código 0, a saída mantém:
   `STRONG = UNAVAILABLE`, `file_operations = BLOCKED_FOR_AGENTS` e
   `agent_execution_authorized = false`.

O executável não fornece interface de chamadas para agentes. O SRT fica
limitado ao processo de canário iniciado explicitamente pelo operador.

## Testes

Novo `test_srt_readonly_pilot.py` cobre política read-only, fixture segura,
argumentos fechados, nonce de saída, negação em subprocesso falso/sem
sandbox, classificações fail-closed, plataforma recusada e obrigatoriedade
de `--synthetic-only`.

O SRT **falso** usado em testes de unidade não prova isolamento; um falso
runtime que executa fora da fronteira deve **falhar** nos controles.

### Procedimento de validação no Arch Linux / Fish

Em checkout limpo desta branch:

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_srt_readonly_pilot.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
```

Depois de testes e inspeção da origem do script, **somente se o operador
decidir executar canários sintéticos**:

```fish
python3 integrations/isolation/srt_readonly_pilot.py --synthetic-only --json
```

Requisitos: Linux/Arch com dependências SRT já instaladas e compatíveis.
Não usar `sudo`, não apontar para sandboxes históricos nem rodar Claude.

### Restrições ainda não atendidas

- `readonly_executor` não é uma ferramenta MCP/Claude nem um executor
  autenticado com aprovação humana; a integração só executa canários
  sintéticos sem dados reais.
- TOCTOU, bind mounts no mesmo dispositivo, file descriptors herdados por
  futuros processos, hardlinks nativos, sockets Unix, DNS, compartilhamento
  de `/tmp/claude` e isolamento entre worktrees/agentes seguem sem prova
  completa neste piloto.
- `allowWrite=[]` restringe a pasta de trabalho mas não comprova ausência
  de outros diretórios temporários internos que o SRT possa permitir.
- Esta implementação não é um sandbox completo, não é condição suficiente
  para `STRONG` e **não libera GH-F1.6, Agent Teams, planner, auditor ou
  implementer**.

**Gates antes de eventual merge**: testes locais completos, execução real
somente fictícia, auditoria Codex independente do diff, revisão humana e
autorização explícita para merge em etapa posterior.
