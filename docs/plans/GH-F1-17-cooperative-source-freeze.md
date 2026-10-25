# GH-F1.17 — Freeze cooperativo da origem em fixture sintética

**Experimento de mitigação parcial, NÃO solução de isolamento.** `STRONG=UNAVAILABLE` e `readiness=BLOCKED`. Não autoriza agentes, operações reais, nuvem, transferência, worktrees reais nem ferramentas nativas do Claude.

## Problema vindo da GH-F1.16

A GH-F1.16 demonstrou `ABA_UNDETECTED`: uma origem fictícia muda A→B→A entre duas leituras de `openat2`, preservando bytes e identidade observados, mas sem provar que estava estável. Também mostrou que um `root_fd` continua acessando uma árvore antiga após seu caminho ser substituído.

**Aumentar o número de leituras não elimina ABA.** Seria preciso estabelecer confiança no proprietário e impedir escritores não confiáveis durante o estágio, o que ainda não existe no toolkit. Esta fase testa apenas um protocolo **cooperativo** e registra explicitamente por que é insuficiente para agentes.

## Protótipo delimitado

`integrations/isolation/synthetic_cooperative_freeze_pilot.py` usa somente `srt_launcher.create_fixture()` e CLI fechada `--synthetic-only [--json]`. Nenhum caminho de usuário é aceito pela CLI; auxiliares Python são exclusivamente internos ao experimento e **não constituem API de segurança**. Não foram modificados `srt_snapshot_pilot.py`, `synthetic_aba_root_fd_probe.py`, `pathguard.py`, `native_boundary_readiness.py`, `toolkit_doctor.py`, as políticas SRT ou agentes.

O protótipo:

1. Abre a raiz **fictícia** via `pathguard.open_root` e cria um lockfile próprio com `O_CREAT|O_EXCL|O_NOFOLLOW`, modo `0600`, link único e dono do processo; nomes existentes, inclusive symlinks/hardlinks, são recusados sem ler seu destino.
2. Adquire `fcntl.flock(LOCK_EX)` sobre esse inode. O descritor fica aberto até a conclusão dos testes, sem `sudo`, shell, `mount` ou subprocessos.
3. Fixa o `root_fd` da origem fictícia e compara `fstat(fd)` com `stat(path, follow_symlinks=False)` antes e depois de `P.stage_snapshot`. Se detectar troca do caminho, recusa com `FreezeRefused`.
4. Sob o lock, valida a integridade do snapshot sintético com `P.host_snapshot_intact`. Somente então libera o lock. Isso **não mantém** imutabilidade após a liberação.
5. Usa uma thread cooperativa com **outro descritor** do mesmo lockfile: o `flock(LOCK_EX|LOCK_NB)` deve falhar enquanto o estágio segura o lock, e a escrita da fonte fictícia só deve ocorrer depois da liberação.
6. Reproduz o limite fatal do mecanismo: uma thread **que ignora `flock`** consegue escrever B e restaurar A no arquivo fictício **enquanto o lock exclusivo está mantido**, pois `flock` é advisory.

## Cinco observações fechadas

| Chave | Observação esperada | Significado |
|---|---|---|
| `fixture_cooperative_snapshot` | `STAGED_UNDER_LOCK` | Snapshot sintético concluído sob bloqueio voluntário |
| `cooperative_writer_waits` | `WRITER_DEFERRED_UNTIL_RELEASE` | Escritor cooperativo não grava enquanto o lock está ativo |
| `root_rebind_fail_closed` | `STALE_PATH_REFUSED` | Troca do caminho de origem detectada e recusada antes de aceitar a cópia |
| `preexisting_lock_refused` | `UNTRUSTED_LOCK_NAME_REFUSED` | Lockfile preexistente/symlink recusado |
| `uncooperative_writer_bypass` | `ADVISORY_BYPASS_REPRODUCED` | Escritor não cooperativo consegue alterar o arquivo apesar do lock — **bloqueador** |

O diagnóstico sempre termina com **exit code 2**, incluindo quando as cinco observações são reproduzidas. Isso impede classificar o canário positivo cooperativo como isolamento `STRONG`. Resultado ausente, exceção, timeout ou tipo malformado é `NOT_VERIFIED`, nunca uma autorização.

O JSON sempre mantém `readiness=BLOCKED`, `strong=UNAVAILABLE`, `agent_execution_authorized=false`, `file_operations_authorized=false`, `cloud_call_authorized=false`, `data_transfer_authorized=false`, `trusted_owner_provenance_verified=false`, `uncooperative_writers_isolated=false`, `aba_protection_proven=false`, `native_tools_isolated_for_agents=false`, `real_bind_mount_tested=false`, `real_worktree_verified=false` e `srt_runtime_revalidated=false`. Razão `UNCOOPERATIVE_WRITE_BYPASS_REPRODUCED` é adicionada quando reproduzida.

## Limitações que ainda bloqueiam o uso real

- `flock` **não impede** `open/write` direto, `rename`, `unlink`, substituição de diretórios, acessos por outros FDs ou escritores que usam lockfiles diferentes. Não temos autoridade sobre todos os escritores possíveis.
- O nome do lockfile sob a fixture é seguro para essa demonstração, **não** um lock que um repositório real de terceiros necessariamente respeitará.
- A comparação `fstat`/`stat` é instantânea e não autentica o proprietário, não evita uma mudança seguida de restauração de caminho (ABA) e não prova proveniência confiável de `root_fd`.
- O snapshot deixa de estar protegido por esse lock ao retornar; diretórios podem ser modificados depois. O piloto não invoca SRT, namespaces, bind mounts ou Read/Edit nativos. **Nenhum caminho de integração com agentes foi habilitado.**
- A reprodução de `ABA_UNDETECTED` pela GH-F1.16 permanece válida; a GH-F1.17 apenas mostra o efeito positivo da colaboração voluntária, não corrige ABA contra um adversário.
- Futuras mitigações precisam avaliar **origem gerida por supervisor confiável**, exclusão real de escritores, estabilidade do destino, namespace privado e testes contra acesso nativo sem cooperação.

## Testes no Arch (Fish)

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_synthetic_cooperative_freeze_pilot.py' -v
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

**Esperado, ainda não executado no Arch:** **45 testes novos**, **188 gerais** e **361 de isolamento** (316 existentes + 45), com nenhum `SKIP` contado como prova positiva.

**Canário separado:** seu código **2 é esperado** e não deve ser encadeado com `and` que exige zero.

```fish
python3 integrations/isolation/synthetic_cooperative_freeze_pilot.py --synthetic-only --json
echo "Código do diagnóstico: $status"
```

Esperadas cinco observações exatas acima, código 2 e todos os bloqueios preservados. Se o sistema não possuir `fcntl` (como no Windows), o módulo pode ser importado e o diagnóstico retorna observações `NOT_VERIFIED` e código 2 sem tentar criar fixtures. Se a criação/inicialização de uma thread falhar (ex.: `RuntimeError` por limitação de recursos), os canários afetados devem registrar `NOT_VERIFIED`, liberar FDs/locks e continuar emitindo relatório bloqueado sem traceback. Se uma vier `NOT_VERIFIED`, há evidência incompleta e a causa deve ser analisada antes de merge.

## Gates

- Escopo **quatro arquivos**: novo piloto, novos testes, este plano e `docs/README.md`, sem tocar nos guardas ou pilotos integrados.
- Operador valida suítes e cenário sintético no HEAD exato no Arch, além de integridade Git.
- A primeira auditoria Codex GPT-6 High identificou **dois P2**: import incondicional de `fcntl` e `Thread.start()`/`join()` quando a thread não inicia. Ambos foram corrigidos na branch, com **oito regressões novas**. É obrigatória nova validação no Arch e nova auditoria do **HEAD corrigido** antes do merge.
- Auditoria independente Codex GPT-6 High, `--sandbox read-only`, com P1/P2 corrigidos e nova revisão se necessário. O Codex talvez não possa executar fixtures em sandbox somente leitura; não confundir com os testes do operador.
- **Merge somente com consentimento explícito para este PR.** PR #9 Draft preservado e `STRONG` sempre indisponível.
