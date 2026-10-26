# GH-F1.18 / PR-B — Boot do supervisor e identidade de raiz sintética

**Estado:** protótipo experimental em Draft PR. **Não é isolamento, autenticação nem autorização.** Implementa apenas o PR-B proposto na [ADR-012](../adr/ADR-012-trusted-snapshot-boundaries.md) (seções 7.1 e 7.2). Invariantes preservadas: `STRONG=UNAVAILABLE`, `readiness=BLOCKED`, `agent_execution_authorized=false`, `file_operations_authorized=false`, `cloud_call_authorized=false`, `data_transfer_authorized=false`. A1 `NOT_VERIFIED`; A3 fora da garantia inicial; ABA sem mitigação completa. Auditorias independentes do Codex: 1ª (HEAD `38adf49`) e 2ª (HEAD `669846e`) com findings corrigidos (seções "Correções após a primeira auditoria" e "Correções após a segunda auditoria"). **Terceira auditoria: PENDENTE.**

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
- CLI fechada `trusted_root.py --synthetic-only [--json]`: toda a sequência (fixture, âncora, abertura, observação, fechamento, remoção) fica sob tratamento de erro; falhas esperadas ou de infraestrutura viram um relatório `REFUSED` sanitizado (só códigos, sem caminhos nem traceback) com saída **2**; uso inválido continua 64. **Falhas de limpeza são observáveis**: `cleanup_failures` ∈ {`anchor_close`, `root_close`, `fixture_remove`}, e o resultado passa a `OBSERVED_WITH_CLEANUP_FAILURE` (nunca `IDENTITY_OBSERVED_NOT_AUTHORIZED`). A criação da fixture é atômica quanto ao resíduo: se `mkdir` ou a escrita do marcador falharem, a fixture parcial é removida e, se a remoção também falhar, `FixtureSetupError` carrega `fixture_remove`. A remoção (`_remove_fixture`) só atua em diretório com o prefixo da fixture, dentro do diretório temporário e que não seja symlink; qualquer outro caminho é recusado sem tocar em nada.
- `check_root_report` valida invariantes com tipos exatos, os códigos de limpeza (ordenados, sem repetição) e a coerência entre `result`, `reason` e `cleanup_failures`.

**`supervisor_boot`**:
- `collect_inventory()`: lê `/proc/self/fd` em processo monothread (`close_range` **não** é usado) e **confronta a listagem com uma sondagem independente** (`fcntl(F_GETFD)` em `0..RLIMIT_NOFILE`, recusada acima de 2^20): FD sondado ausente da listagem, ou mais de um número listado que não existe mais (o da própria listagem), ou descrição instável entre duas leituras, tornam o inventário inconsistente. Identidade do procfs: `readlink /proc/self` e `/proc/self/stat` precisam coincidir com o pid. Um FD sentinela `/dev/null` aberto na coleta deve reaparecer com a identidade esperada. Uma segunda listagem precisa coincidir com a primeira dentro do intervalo sondado. Alvos que são caminhos de arquivo são redigidos.
- **Validação semântica do inventário** (`_validate_inventory`): além dos tipos, exige `probe_range` em [3, 2^20], FDs estritamente crescentes (sem duplicata) e dentro do intervalo sondado, `access` e `opath` coerentes com `flags`, `transient == 1` quando `probe_agrees`, e `sentinel_verified` quando `structurally_consistent`. Combinações contraditórias → `inventory_contradictory`; sucesso não declarado → `inventory_inconsistent`; forma inválida → `inventory_malformed`. **Passar nessa validação não dá proveniência**: um dicionário recebido de fora continua dado não confiável; o relatório registra `inventory_provenance` (`collected_in_process`, `caller_supplied_unverified` ou `none`).
- **Três conceitos distintos.** (1) *Inventário estruturalmente consistente*: listagem, sondagem e metadados concordam nesta observação (`inventory_structurally_consistent`). (2) *Inventário efetivamente completo*: **não comprovável** (corridas, `/proc` adulterado de forma coerente com a sondagem); o relatório afirma sempre `inventory_effectively_complete=false`. (3) *Ausência de capacidades não observadas*: **não comprovada**; `unobserved_capabilities_excluded=false`. `CLEAN_FOR_GRANTS` significa apenas "nenhum FD observado é desconhecido".
- `CapabilityRegistry`: **não há API de declaração.** Não existe método que aceite um FD já existente: `place_devnull(0|1|2)` e `make_pipe()` criam o FD, ancoram e só então emitem o grant (`_issue` recusa tudo que não seja um recibo criado por essas fábricas — inclusive um `int`, um `Grant` montado à mão ou um recibo forjado: `declaration_refused`). `grants` é uma visão somente leitura, a classe usa `__slots__`, a avaliação aceita apenas o tipo exato `CapabilityRegistry`, só confia em grants que **este** registro emitiu e revalida cada um (tipos, `kind`, âncoras distintas). `_MINT`, `_mint_grant`, `_registry_with` e `_record` **não existem** no módulo de produção; os testes puros montam registros sintéticos com um helper local que escreve no estado privado (o que código no mesmo processo sempre poderia fazer). **Limite explícito:** isto fecha o caminho de concessão por declaração da interface operacional; não é fronteira contra código Python arbitrário no mesmo processo (A3, fora da garantia).
- **Ciclo de vida do registro.** `close()` (idempotente; também como gerenciador de contexto) fecha as âncoras privadas, esvazia os grants e invalida o registro: a avaliação recusa `registry_closed` e as fábricas também. Os FDs entregues ao chamador (pipes, slots 0-2) não são fechados. `make_pipe` é tudo-ou-nada (qualquer falha fecha os dois FDs e as âncoras e não emite grant). Se `place_devnull` falhar depois do `dup2`, o slot permanece como `/dev/null` herdável **sem grant** (a autoridade herdada anterior já foi descartada e não é restaurável); se o slot estava fechado e foi reutilizado, volta a ficar fechado. Nenhum caminho deixa FD vazado. Número de FD reutilizado após `close` é detectado por identidade/OFD.
- **Direitos, não só identidade.** Cada `Grant` guarda `kind`, `dev`, `ino`, `flags` completos (`F_GETFL`: modo de acesso, `O_PATH`, `O_APPEND`...), estado `inheritable` (↔ `FD_CLOEXEC`) e um **dup privado (âncora, FD ≥ 3, CLOEXEC)** da mesma open file description. A classificação compara tudo estritamente e usa `kcmp(KCMP_FILE)` entre o FD e a âncora para detectar troca de open file description (inclusive reabertura do mesmo inode). Se `kcmp` não puder ser executado, o grant é `unknown` (`ofd_unverifiable`), nunca autorizado por falta de informação. As âncoras aparecem no inventário e são contabilizadas como `registry_anchor` (e viram `unknown` se perderem CLOEXEC ou identidade).
- `place_devnull(0|1|2)`: abre um `/dev/null` **novo** (não duplica FD herdado), verifica `S_ISCHR` e `rdev==1:3`, trata explicitamente o caso em que `open()` reutiliza o número do slot fechado (onde `dup2(fd, fd)` não alteraria flags: chama `set_inheritable(True)`), valida o estado efetivo (`chr_devnull`, sem CLOEXEC, `rdwr`, sem `O_PATH`) e, se falhar, levanta `BootRefused` devolvendo fechado o slot que ela mesma abriu. Limite de confiança: o `/dev/null` do namespace atual; não protege contra quem controla `/dev`.
- `evaluate(inventário, registro)` valida o inventário (chaves e tipos exatos, sem duplicata, `kind` conhecido), classifica cada FD (inclusive 0, 1 e 2) como `authorized`/`unknown` com a lista `mismatch` dos atributos que divergiram (`identity`, `access`, `opath`, `flags`, `cloexec`, `ofd`, `ofd_unverifiable`). FD 0/1/2 fechado ou grant sem FD impedem veredito limpo. `diagnose(registro)` não aceita coletor injetável, nunca levanta e converte exceção/ausência/saída malformada em `REFUSED`.
- Relatórios: `_report` não aceita campos reservados (`ValueError`), compõe as invariantes a partir de `INVARIANTS` (visão somente leitura) e passa por `check_boot_report`, que chama `check_report` (tipos exatos: `strong`, `readiness`, as quatro autorizações; `bootstrap_trusted`, `bootstrap_complete`, `inventory_effectively_complete` e `unobserved_capabilities_excluded` = `false` quando presentes) e recusa combinações contraditórias de `verdict`, `inventory_structurally_consistent`, `unknown_fds`, `std_closed`, `grants_missing`, `entries` e `reason`. Vereditos: `CLEAN_FOR_GRANTS`, `UNKNOWN_CAPABILITIES`, `REFUSED`; **nenhum** significa bootstrap confiável. Campos fora do schema de um relatório não são adicionados artificialmente.
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

Plataforma/arquitetura não suportada; syscall ausente; âncora ou FD inválido/fechado; arquivo regular no lugar do diretório; symlink no lugar da raiz ou do marcador; raiz renomeada/substituída/removida; identidade divergente; campo obrigatório de `statx` ausente; sem identificador de montagem; `ino`/`dev` inconsistentes; observação instável; mountpoint (simulado e `/proc` real); inventário inconsistente (FD real omitido, transitório falso, instável), malformado ou com falha de syscall; procfs/pid divergente; processo multithread; `RLIMIT_NOFILE` ilimitado; capability de tipo não prevista; registro forjado; FD extra herdado; objeto sensível em 0/1/2; grant trocado por outro objeto (extremo de pipe, mesmo inode reaberto); `/dev/null` que não é 1:3; falhas de infraestrutura e de limpeza da CLI.

## Testes e condições

A classificação é **por classe de teste**; cada teste está em exatamente uma categoria e o total não duplica contagens. "Real" significa que o comportamento vem do kernel; em "misto" a preparação/controle usa syscalls reais, mas o finding principal depende de uma falha injetada (mock) e, portanto, **não** prova o kernel.

| Categoria | `test_trusted_root` | `test_supervisor_boot` | Total | O que prova |
|---|---|---|---|---|
| Kernel/sistema de arquivos reais, no processo, sem mocks (`KernelTests`, `CleanupRealTests`) | 15 | 0 | 15 | openat2/statx reais e remoção segura de fixtures |
| Subprocesso real, sem mocks (`CliSubprocessTests`, `ChildProcessTests`) | 2 | 15 | 17 | `/proc/self/fd`, fcntl, kcmp, fábricas e CLI em filhos descartáveis |
| Misto: real + falha injetada (`MixedTests`, `CliFaultInjectionTests`, `ChildMixedTests`) | 24 | 6 | 30 | lógica do programa sob falha; não o kernel |
| Lógica pura / dados sintéticos (`PureMockTests`, `PureLogicTests`) | 6 | 26 | 32 | lógica do programa |
| **Total novo** | **47** | **47** | **94** | |

Os testes que alteram FDs (dup2, close, pipes, herança) rodam **apenas** em subprocessos `python -I` descartáveis; o processo do operador e o terminal nunca são alterados. Timeout ou saída malformada do filho falha o teste. Um `skip` por syscall indisponível (ex.: `kcmp`) não é evidência positiva.

### Resultados por ambiente

| Ambiente | Execução | Resultado |
|---|---|---|
| Container do desenvolvimento (Linux 6.18, Python 3.13, x86_64) | 94 testes novos; suíte `integrations/isolation` 455 (361 anteriores + 94); `tests/` 188; skips: 0 | todos OK |
| Arch Linux do proprietário (ext4, kernel 7.2.4), informado por Arthur, **no HEAD `669846e`** | 431 testes de isolamento, 188 gerais, as duas CLIs `--synthetic-only` | OK; CLIs com código 2 e todas as autorizações `false`. **Anterior às correções desta rodada: precisa ser revalidado.** Não comprova isolamento operacional |

Nenhum resultado do container é apresentado como execução no Arch. Os 94 testes do HEAD atual **ainda não foram executados no Arch**.

O único teste de mountpoint real só **atravessa** `/proc` (já montado) e é recusado; nenhum mount foi criado.

## Correções após a primeira auditoria

Primeira auditoria Codex sobre o HEAD `38adf49`: findings corrigidos nesta rodada (relatório integral não disponível nesta sessão; correções derivadas da lista de findings repassada pelo proprietário).

| Finding | Correção | Evidência |
|---|---|---|
| `registry.grants` modificável | visão somente leitura, `__slots__`, tipo exato do registro, revalidação (o token de criação desta rodada foi **substituído** na segunda auditoria: ver abaixo) | `test_registry_cannot_be_forged_*` |
| Grants comparados só por kind/dev/ino/CLOEXEC | flags completos, `inheritable`, âncora + `kcmp(KCMP_FILE)`; sem `kcmp` ⇒ `unknown` | testes de direitos e de OFD |
| `place_devnull` com slot fechado e número reutilizado | caso tratado explicitamente, estado efetivo validado, falha fechada | 3 slots × (substituição, slot fechado, falha injetada) |
| Sentinela + 1 transitório vendidos como "completo" | sondagem fcntl independente, releitura de estabilidade, `/proc/self/stat`; campos renomeados e `inventory_effectively_complete` fixo em `false` | listagem com FD real omitido recusada |
| `INVARIANTS`/`_report` mutáveis | `MappingProxyType`, campos reservados recusados, `check_report`, `diagnose` sem coletor injetável | testes negativos de sobrescrita |
| CLI `trusted_root` com falhas fora do `try` | `_run_synthetic` total, saída sanitizada, `cleanup_failures` | 11 testes de injeção + falta real de FDs |

## Correções após a segunda auditoria

Segunda auditoria Codex sobre o HEAD `669846e` (texto integral não disponível nesta sessão; correções derivadas do resumo de estado repassado pelo proprietário, sem findings inventados): grants, inventário, invariantes e CLI `trusted_root` **parcialmente resolvidos**; direitos/`kcmp`, `place_devnull` e classificação dos testes **resolvidos** (preservados, com testes mantidos).

| Grupo | Problema | Correção | Evidência |
|---|---|---|---|
| Grants (P1) | `_record()` aceitava FD já aberto; `_MINT`, `_mint_grant`, `_registry_with` no código de produção | nenhuma API de declaração; recibos criados só pelas fábricas; helpers removidos; grants só valem se emitidos pelo próprio registro; ciclo de vida (`close`) | declaração de 0/1/2 herdados, de `int`, de `Grant` à mão e de recibo forjado ⇒ `declaration_refused`; nada concedido; controle positivo das fábricas |
| Inventário | relações entre campos não validadas | validação semântica (seção acima) e `inventory_provenance` | dezenas de inventários contraditórios/malformados recusados com o código certo |
| Invariantes | `check_report` não cobria os campos de completude | `check_report` + `check_boot_report` + `check_root_report` com tipos exatos e coerência de veredito | adulteração de cada campo (`True`, `1`, `0`, `"false"`, `None`), campo ausente, veredito incompatível, estrutura malformada, falha inesperada ⇒ recusa |
| CLI `trusted_root` / cleanup | falha de limpeza da fixture parcial não propagada; `rmtree(ignore_errors=True)` | `FixtureSetupError`, `_remove_fixture` restrito, `root_close`, resultado `OBSERVED_WITH_CLEANUP_FAILURE` | falhas em `mkdir`, escrita do marcador, remoção e combinações consecutivas; resíduo declarado |
| Recursos do registro | vazamento de âncoras / FDs em falhas parciais | `make_pipe` tudo-ou-nada, rollback de âncoras, `close()` idempotente, tratamento de `place_devnull` após `dup2` | diff de FDs do filho = vazio após cada falha injetada |

### Reproduções adversariais (código real em subprocesso descartável, salvo indicação)

- **Extremos de pipe trocados** (`make_pipe()`, controle `CLEAN_FOR_GRANTS`, depois `dup2(w, r, inheritable=False)` e o inverso): o FD trocado vira `unknown`. `kind`, `dev` e `ino` são idênticos nos dois extremos e `CLOEXEC` foi preservado de propósito, logo **não** distinguem; diferenciaram `access` (`O_RDONLY` × `O_WRONLY` em `F_GETFL`) e `ofd` (`kcmp`): `mismatch = {access, ofd}`. Com `dup2` comum acrescenta-se `cloexec`.
- **Reabertura do mesmo inode:** só `ofd` diferencia (`mismatch = {ofd}`).
- **Número de FD reutilizado após `close`:** outro objeto no mesmo número ⇒ `unknown` (`identity` + `ofd`).
- **Listagem adulterada** (mock injetado no filho, syscalls reais): omitir um FD real mantendo sentinela e transitório; omitir o real e trocar o transitório por um falso; transitório extra ⇒ `REFUSED inventory_inconsistent`. Trocar só o número transitório segue consistente (sem afirmar completude).
- **`kcmp` indisponível** (arquitetura trocada no filho, de modo que a chamada real devolve "indisponível"): todos os grants viram `unknown` (`ofd_unverifiable`), nunca `authorized`.
- **Falhas parciais** (`fcntl(F_DUPFD_CLOEXEC)` falhando no filho): `place_devnull` deixa o slot como `/dev/null` herdável sem grant (ou fechado, se estava fechado) e `make_pipe` não deixa nada; em ambos o conjunto de FDs do filho é idêntico ao anterior.
- **Mutações verificadas manualmente (testes falham):** aceitar `int` em `_issue`; remover a checagem de `opath`; remover `transient == 1`; trocar `inventory_effectively_complete` para `true`; remover a checagem de prefixo em `_remove_fixture`; ignorar a falha de limpeza da fixture parcial; (da rodada anterior) desligar `probe_agrees` e o `set_inheritable`.

## Resultados não verificados

Execução dos 94 testes no Arch/ext4/kernel 7.2.4, completude real de inventário (impossível de provar), `kcmp` bloqueado por seccomp/sandbox (resulta em `unknown`), raiz sob mount real do projeto, bind mounts, namespace diferente, `STATX_MNT_ID_UNIQUE` em kernel < 6.8 (caminho `legacy` só exercitado com mock), WSL2, macOS, comportamento no kernel 7.2.4/ext4 do proprietário, execução em terminal interativo real, SRT com FDs preexistentes.

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

Verificar a terceira rodada: ausência de qualquer caminho de concessão por declaração na interface operacional, ciclo de vida/rollback do registro, validação semântica do inventário, `check_*_report` e a limpeza da fixture; verificar se algum caminho transforma `CLEAN_FOR_GRANTS` ou `IDENTITY_OBSERVED_NOT_AUTHORIZED` em autorização; se `place_devnull` pode propagar autoridade herdada; completude do inventário sob threads e corridas; mapeamento de errno do `openat2`; reexecutar no Arch/ext4/7.2.4.
