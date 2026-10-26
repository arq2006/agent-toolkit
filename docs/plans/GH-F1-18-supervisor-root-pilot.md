# GH-F1.18 / PR-B — Boot do supervisor e identidade de raiz sintética

**Estado:** protótipo experimental em Draft PR. **Não é isolamento, autenticação nem autorização.** Implementa apenas o PR-B proposto na [ADR-012](../adr/ADR-012-trusted-snapshot-boundaries.md) (seções 7.1 e 7.2). Invariantes preservadas: `STRONG=UNAVAILABLE`, `readiness=BLOCKED`, `agent_execution_authorized=false`, `file_operations_authorized=false`, `cloud_call_authorized=false`, `data_transfer_authorized=false`. A1 `NOT_VERIFIED`; A3 fora da garantia inicial; ABA sem mitigação completa. Auditoria independente do Codex: **PENDENTE**.

## Arquivos

| Arquivo | Papel |
|---|---|
| `integrations/isolation/trusted_root.py` | abre e identifica uma raiz **sintética** pelo kernel |
| `integrations/isolation/supervisor_boot.py` | inventário e classificação de FDs herdados |
| `integrations/isolation/test_trusted_root.py`, `test_supervisor_boot.py` | testes positivos e negativos |

Nenhum módulo histórico, política, doctor, readiness ou gate foi alterado.

## Contratos implementados

**`trusted_root`** (todos recusam com `RootRefused(código)`):
- `open_synthetic_root(anchor_fd, name)`: `openat2` de **um componente** sob um FD âncora com `BENEATH|NO_SYMLINKS|NO_MAGICLINKS|NO_XDEV` e `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. Só aceita nomes com prefixo `gh-f1-18-synthetic-` e pasta com o marcador `.gh-f1-18-synthetic`. São guardas contra uso acidental, **não prova de origem**; o piloto não aceita caminho de projeto como entrada operacional.
- `observe(fd)`: `fstat` → `statx(fd, "", AT_EMPTY_PATH)` → `fstat`. Exige `STATX_TYPE` e `STATX_INO` em `stx_mask`; não exige `STATX_DEV` (não existe) e compara `dev` de `statx` com o de `fstat`. Pede `STATX_MNT_ID_UNIQUE`; se o bit não voltar, repete com `STATX_MNT_ID`. Registra a variante (`unique` | `legacy`); sem nenhuma, recusa (`identity_incomplete`).
- `compare(a, b)`: igualdade de `dev`, `ino`, `mnt_id`; variantes diferentes (`variant_not_comparable`) ou namespace de montagem desconhecido/diferente recusam.
- `OpenedRoot.revalidate_fd()` e `reopen_and_compare(anchor_fd, name)`; só a segunda enxerga renomeação/rebind (FD obsoleto continua válido para si mesmo).
- CLI fechada `trusted_root.py --synthetic-only [--json]`, sempre código de saída 2.

**`supervisor_boot`**:
- `collect_inventory()`: lê `/proc/self/fd` em processo monothread (`close_range` **não** é usado), com `fstat`, `readlink`, `F_GETFD` (CLOEXEC) e `F_GETFL`. Um FD sentinela `/dev/null` aberto na coleta deve reaparecer com a identidade esperada e exatamente um FD transitório (o da listagem) deve sumir; caso contrário `complete=false`. Alvos que são caminhos de arquivo são redigidos no relatório.
- `CapabilityRegistry`: grants **só** nascem das fábricas (`place_devnull(0|1|2)`, `make_pipe()`), que criam o FD no próprio processo; não existe "registrar FD herdado". Um grant só autoriza se `kind`, `dev`, `ino` e CLOEXEC ainda conferem.
- `evaluate(inventário, registro)` valida o inventário (completo, tipos exatos, sem duplicata, `kind` conhecido) e classifica cada FD (inclusive 0, 1 e 2) como `authorized` ou `unknown`. FD 0/1/2 fechado ou grant sem FD impedem veredito limpo. `diagnose()` nunca levanta: exceção, ausência ou saída malformada viram `REFUSED`.
- Vereditos: `CLEAN_FOR_GRANTS`, `UNKNOWN_CAPABILITIES`, `REFUSED`. **Nenhum** significa bootstrap confiável: `bootstrap_trusted` e `bootstrap_complete` são sempre `false`.
- CLI fechada `supervisor_boot.py --synthetic-only [--json]`, só leitura, sempre saída 2.

## Contratos NÃO implementados

Concessão do proprietário e autenticação, célula SRT real, Apply Gate, store de snapshots, harness de testemunhas (PR-C), captura (PR-D), fechamento/reposicionamento de FDs, sanitização de ambiente/`cwd`, `setsid`, `no_new_privs`, IPC/`SCM_RIGHTS`, mount namespaces reais.

## Fronteiras de confiança

Confia-se no kernel, no Python do sistema, em `/proc` e no código deste repositório. O FD âncora é **suposto** (proveniência `NOT_VERIFIED`). Conteúdo da raiz sintética, nomes e relatórios do filho são dados. Escritores do mesmo UID (A3) e root/kernel (A4) estão fora da garantia.

## Modelo de identidade da raiz

Tupla `(dev, ino, mnt_id, variante, mnt_ns)` observada no FD já aberto. Serve **apenas para comparar** observações. Não autentica o proprietário, não exclui escritores externos, não protege contra ABA e não prova que o FD corresponde ao nome atual.

## Limitações de openat2/statx

- `NO_XDEV` é recusa: um mountpoint legítimo também dá `xdev_refused`; não é relaxado.
- Os campos de um `statx` e as três chamadas de `observe` não são atômicos; divergência visível é detectada, a corrida não é eliminada.
- `stx_dev_*` não tem bit; a coerência com `fstat` é verificada e a divergência recusa.
- IDs únicos e legados de montagem não são comparáveis entre si; o escopo por mount namespace não está documentado e o link de `/proc/self/ns/mnt` é só contexto.
- Arquiteturas: x86_64 e arm64; outras são recusadas. Falta de syscall (ENOSYS/EPERM/EINVAL) recusa, sem fallback.

## Casos de recusa cobertos

Plataforma/arquitetura não suportada; syscall ausente; âncora ou FD inválido/fechado; arquivo regular no lugar do diretório; symlink no lugar da raiz ou do marcador; raiz renomeada/substituída/removida; identidade divergente; campo obrigatório de `statx` ausente; sem identificador de montagem; `ino`/`dev` inconsistentes; observação instável; mountpoint (simulado e `/proc` real); inventário incompleto, malformado ou com falha de syscall; capability de tipo não prevista; FD extra herdado; objeto sensível em 0/1/2; grant trocado por outro objeto.

## Testes e condições

Ambiente de desenvolvimento do PR: Linux 6.18 (container), Python 3.13, `/tmp` em filesystem local. O ambiente do proprietário (Arch, ext4, kernel 7.2.4) **não** foi usado.

| Categoria | Qtde | O que prova |
|---|---|---|
| Kernel real (`KernelTests`, openat2/statx em fixtures em `/tmp`) | 13 | comportamento real das syscalls nesse kernel |
| Subprocesso real (`ChildProcessTests`, `/proc/self/fd` de filhos descartáveis) | 8 | inventário real; nenhum FD do operador é modificado |
| Mocks / dados sintéticos (`MockTests`, `InventoryLogicTests`) | 23 | apenas a lógica do programa, não o kernel |

Total novo: 44. Suíte `integrations/isolation`: 405 (361 anteriores + 44). Suíte `tests/`: 188 (inalterada). Um `skip` por syscall indisponível não é evidência positiva (nenhum ocorreu nesta execução). O único teste de mountpoint real só **atravessa** `/proc` (já montado) e é recusado; nenhum mount foi criado.

## Resultados não verificados

Raiz sob mount real do projeto, bind mounts, namespace diferente, `STATX_MNT_ID_UNIQUE` em kernel < 6.8 (caminho `legacy` só exercitado com mock), WSL2, macOS, comportamento no kernel 7.2.4/ext4 do proprietário, execução em terminal interativo real, SRT com FDs preexistentes.

## Por que isto não desbloqueia STRONG

STRONG exige célula isolada validada com controles positivos e negativos de leitura, escrita e rede, concessão do proprietário e Apply Gate. Aqui há apenas identificação de um diretório sintético e inventário de FDs de um processo. Sucesso destes testes **não** é autorização operacional.

## Validação

```bash
python3 -I -m unittest discover -s integrations/isolation -p 'test_trusted_root.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_supervisor_boot.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 integrations/isolation/trusted_root.py --synthetic-only --json; echo $?        # esperado 2
python3 integrations/isolation/supervisor_boot.py --synthetic-only --json; echo $?     # esperado 2
git diff --check main...HEAD && (cd docs && sha256sum -c CHECKSUMS.sha256)
```

## Recomendações para a auditoria Codex

Verificar se algum caminho transforma `CLEAN_FOR_GRANTS` ou `IDENTITY_OBSERVED_NOT_AUTHORIZED` em autorização; se `place_devnull` pode propagar autoridade herdada; completude do inventário sob threads/`/proc` adulterado; mapeamento de errno do `openat2`; reexecutar no Arch/ext4/7.2.4.
