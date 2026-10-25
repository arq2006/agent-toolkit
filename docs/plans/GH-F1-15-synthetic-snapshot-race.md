# GH-F1.15 — Canário de concorrência/TOCTOU em snapshot sintético

**Estado:** experimento somente com fixture descartável. Não autoriza nenhum agente, caminho real, cloud, leitura nativa de projetos ou `STRONG`. Permanece `readiness=BLOCKED`, `strong=UNAVAILABLE`.

## Risco confirmado no código GH-F1.14

O `stage_snapshot` original validava o arquivo fonte com `stat` antes e depois de uma única leitura `openat2`. Se outra thread escrevesse **bytes diferentes do mesmo tamanho no mesmo inode após a leitura**, os valores `st_dev`, `st_ino`, `st_size` e `st_nlink` poderiam continuar idênticos. A comparação de metadados **não comprova integridade do conteúdo** ao longo dessa janela. Mesmo quando o marcador da fixture original é validado na primeira leitura, uma mutação subsequente poderia passar despercebida.

## Alteração mínima ao piloto existente

`integrations/isolation/srt_snapshot_pilot.py` agora faz uma **segunda leitura guardada `G.read_bytes`** de `canary_read.txt` e rejeita qualquer divergência dos bytes da primeira leitura. Também compara os metadados do arquivo antes, entre e após as leituras. Caso algum valor não coincida, o próprio estágio sintético recusa com `SnapshotRefused("source_not_stable")` (ou com erro fail-closed do guard).

Essa é **detecção parcial e não garantia de imutabilidade**. Uma alteração revertida entre observações (ABA), uma troca de conteúdo depois da última verificação, alterações nos ancestrais ou problemas de proveniência de `root_fd` ainda podem não ser detectados. Não ler, copiar nem autorizar diretórios reais com essa API.

## Canário cooperativo de concorrência

`integrations/isolation/srt_snapshot_race_probe.py` tem CLI **somente `--synthetic-only [--json]`**. Para cada caso:

- Cria uma fixture nova por `srt_launcher.create_fixture()`; nunca recebe um caminho arbitrário.
- Uma **thread separada** faz uma única alteração de arquivo fictício na fase exata de leitura/escrita, coordenada por três `threading.Event` (`fire`, `finished` e `cancel`) e timeout. O worker de ataque deve realmente disparar e concluir; se não, o teste falha.
- Os pontos de injeção são somente substituições temporárias de `G.read_bytes` e `_write_all` por wrappers de teste usando `unittest.mock`, restritas ao processo do canário. O código de produção de `srt_snapshot_pilot` não ganha callbacks ou comandos externos.
- **Não inicia SRT, subprocessos, shell, redes, mount, namespaces, agentes ou Codex**. O SRT real já foi ensaiado separadamente na GH-F1.14; este experimento visa apenas concorrência no estágio local.

Os **seis cenários fixos** são:

1. `baseline`: controle positivo; snapshot autorizado funciona sem ataque.
2. `source_inplace_same_size`: após a primeira leitura, a thread troca o conteúdo por bytes da mesma quantidade, sem modificar inode ou tamanho. A segunda leitura deve detectar a alteração e recusar.
3. `source_symlink_before_read`: substitui a fonte por symlink antes da leitura; `openat2` deve recusar.
4. `source_hardlink_before_recheck`: troca a fonte por hardlink para o decoy antes da segunda leitura; recusar.
5. `target_symlink_after_write`: altera o caminho de saída para symlink antes da verificação do destino; recusar.
6. `target_hardlink_after_write`: cria um hardlink extra para o arquivo de saída entre escrita e checagem; `st_nlink != 1` deve reprovar.

Cada cenário tem `PASS` **somente** quando o comportamento esperado ocorreu: no controle positivo, cópia intacta; nos cinco negativos, ataque confirmado e estágio recusado. Ataque não disparado, falha de thread, timeout, recusa indevida do controle ou retorno malformado não gera `PASS`.

## Interpretação dos resultados

O CLI retorna código `0` quando **6/6 verificações** passam na fixture do host, senão `2`. **Mesmo código `0` não permite `STRONG`**; as flags `agent_execution_authorized`, `file_operations_authorized`, `cloud_call_authorized`, `data_transfer_authorized` e `native_tools_isolated_for_agents` permanecem `false`. O relatório explicita `arbitrary_concurrency_proven=false`, `real_bind_mount_tested=false` e `srt_runtime_revalidated=false`.

Limites importantes: há interleavings **cooperativos e determinísticos**, não um atacante arbitrário capaz de montar caminhos, abrir outros FDs, abusar de mudanças na árvore após o estágio ou usar interfaces nativas de Claude. O teste não demonstra comportamento sob milhões de operações, múltiplos processos não cooperativos nem sabotagem real do host; o isolamento ainda exige namespaces e componentes de confiança que não foram construídos.

## Testes no Arch Linux (Fish)

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_srt_snapshot_race_probe.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_srt_snapshot_pilot.py' -v
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

Contagens esperadas, **pendentes de validação no Arch**: **27 testes novos**, **40 regressões GH-F1.14**, **188 gerais** e **286 de isolamento** (259 atuais +27). Em máquina sem `openat2` válido, testes dependentes do kernel podem fazer `SKIP`, **não** contar como prova positiva.

Após os testes, canário de corrida (fixture-only):

```fish
python3 integrations/isolation/srt_snapshot_race_probe.py --synthetic-only --json
echo "Código do canário: $status"
```

Esperado no Arch Linux: seis casos `PASS`, código `0`, `STRONG=UNAVAILABLE`, `readiness=BLOCKED`. Não há necessidade de sudo ou execução do SRT; **não usar dados reais**, não executar em repositórios externos. Um `FAIL` ou `2` exige correção antes de qualquer merge.

## Gates

- Verificar 5 arquivos alterados apenas: `srt_snapshot_pilot.py`, novo `srt_snapshot_race_probe.py`, novo teste, este plano e `docs/README.md`.
- Rodar suítes e canário no Arch no HEAD exato, com captura dos casos e contagem dos testes.
- Reauditar no Codex GPT-6 High read-only, corrigir P1/P2 e repetir provas conforme necessário.
- Merge **somente** mediante autorização humana específica a este PR.
- Nenhum `STRONG=AVAILABLE`, uso de agente, cloud fallback, worktree real, montagem de bind ou desativação de sandbox.
