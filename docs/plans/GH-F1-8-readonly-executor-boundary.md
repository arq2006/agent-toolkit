# GH-F1.8 / PR4 — Interface read-only fechada sobre pathguard

**Status:** prototipo de biblioteca e testes, **nao ligado a agentes**. Nunca muda o status
atual do doctor: `agent_execution_authorized = false`, `file_operations = BLOCKED`,
`strong = UNAVAILABLE`. Nao constitui aceite da GH-F1.5 e nao libera GH-F1.6.

## Por que esta mudanca

No Arch Linux, o `toolkit_doctor` (srt 0.0.81, bwrap 0.12.0) concluiu os
canarios obrigatorios com codigo 0 numa fixture sintetica. O teste **reproduziu
uma leitura de conteudo externo via hardlink preexistente** dentro da raiz
autorizada, embora as leituras pelo caminho externo fossem bloqueadas.

O `pathguard` da main ja tinha `read_bytes`, `list_dir` e `scan_tree`,
que recusam symlink/hardlink/tipo especial no escopo declarado. Esses controles
NAO interceptam ferramentas nativas `Read/Grep/Glob/Write/Edit` do Claude.
Por isso o hardlink segue um bloqueio de seguranca real para a estrategia de
ferramentas nativas.

Documentacao upstream:
- https://github.com/anthropics/sandbox-runtime — filesystem.read deny/allow e
  limite dos hardlinks existentes nos bind mounts no Linux
- [ADR-011](../adr/ADR-011-isolamento-do-processo.md) — condicoes para STRONG
- [Reconciliacao GH-F1.5](../pilotos/GH-F1-5-reconciliacao-2026-10-24.md)
  — provas de paralelismo e lacunas dos probes anteriores

## Decisao proposta para a proxima arquitetura

**Preferir o caminho coordenador sem ferramentas de filesystem + contrato JSON
estrito + executor dentro do SRT**, com `pathguard` em cada operacao, ao inves
de declarar que SRT sozinho torna `Read/Edit` nativos seguros.

Essa decisao **nao foi ativada** nesta entrega. O coordenador autenticado fora
da fronteira, quando escolhido, **nao e isolamento integral**; documentar a
fronteira, impedir que receba capacidades de leitura direta e submeter a
arquitetura a revisao antes de qualquer uso real.

**Proibido neste prototipo:** repassar texto da IA a shell, comandos dinamicos,
permitir `Read/Grep/Glob` nativos em paralelo, usar paths absolutos ou `..`,
escrever arquivos, iniciar agente, abrir rede ou instalar componentes.

## Interface implementada (biblioteca, sem CLI)

`integrations/isolation/readonly_executor.py` expõe apenas:

- `parse_request(raw: bytes)`: JSON UTF-8 de ate 4096 bytes, sem duplicatas,
  NaN, campos extras ou formatos implicitamente convertidos.
- `dispatch(root_fd, request)` e `dispatch_json(root_fd, raw)`: somente
  `{"op":"read","path":"arquivo.txt"}`, `{"op":"list"}` e
  `{"op":"list","path":"subpasta"}`. `root_fd` deve vir de
  `pathguard.open_root` depois de configuracao/autorizacao externa, nunca de
  um valor recebido do modelo.
- `read` usa `pathguard.read_bytes` e aceita somente texto UTF-8 ate
  64 KiB. `list` usa `pathguard.list_dir` e limita resposta a 1024 entradas.
  Erros reportam codigos estaveis, sem nomes dos arquivos nem conteudo.
- A cada solicitacao chama `pathguard.scan_tree` (ate 20000 entradas).
  Achados de symlink, hardlink, arquivo especial ou outro dispositivo
  recusam a operacao integralmente; excesso de entradas/erros tambem recusa.
  Isso e **higiene adicional**, e nao uma prova sem corrida.

O modulo **nao e um launcher**, nao possui `if __name__ == "__main__"`, nao
registra ferramenta no Claude e nao modifica `srt_launcher.py`,
`toolkit_doctor.py`, `.claude/`, permissoes ou hooks. Chamadas de biblioteca
em processo sem SRT **nao estao isoladas**. Os testes usam apenas diretorios
temporarios ficticios.

## Limites e gates mantidos

1. **Hardlinks nativos ainda vulneraveis.** Um `Read` nativo fora deste
   dispatcher continuaria podendo acessar dados via hardlink. A correcao
   proposta so vale quando o caminho nativo estiver comprovadamente
   **indisponivel** e toda leitura passar pelo `pathguard`.
2. **TOCTOU:** varredura e uso nao sao atomicos. Uma arvore pode mudar entre
   `scan_tree` e `read/list`. `pathguard` reabre componentes com
   `O_NOFOLLOW` e verifica `st_nlink`, mas isso nao resolve todos os casos
   de mudanca simultanea. Nao pontuar como STRONG.
3. **Bind mounts:** mount do mesmo dispositivo pode escapar da comparacao
   `st_dev`; a validacao da arvore nao demonstra ausencia de mounts
   preexistentes nem de trocas de mount namespaces.
4. **FD e autenticacao:** caller deve garantir raiz autorizada, origem do FD,
   SRT iniciado com politica revisada, ausencia de credenciais e rede externa,
   implementacao sem comandos arbitrarios. Ainda nao integrado nem exercitado
   com Claude.
5. **Observabilidade e auditoria:** falta execucao sob SRT, negativos de
   hardlink sob os fluxos integrais, testes de concorrencia, controle de
   chamadas, aprovacoes, revisao humana e auditoria independente Codex da fase
   pertinente. Nenhuma escrita por agentes esta autorizada.

## Validacao local proposta (Arch / Fish)

Em checkout limpo desta branch, sem executar Claude:

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_readonly_executor.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
```

**Testes nesta entrega:** cobrirem leitura/listagem permitidas; JSON e caminhos
invalidos; negacao de operadores de escrita, shell e rede; symlink/hardlink
em fixture externa; FIFO; limite de tamanho de entrada, arvores e resultados;
arquivo binario; FD nao-diretorio; rechecagem entre chamadas. O run local
ainda precisa ser registrado pelo operador antes de qualquer aceite.

## Nao executar ainda

- `claude -p`, `planner`, `auditor`, `implementer` ou Agent Teams.
- `toolkit_doctor` fora de fixture sintetica (ele ja foi executado com
  sucesso e sua limitacao de hardlink foi reproduzida).
- Migracao, limpeza ou alteracao no sandbox historico `/home/agent-pilot`.
- Chamada a `dispatch_json` com dados de projetos reais ou credenciais.
