# GH-F1.18 / PR-B — Boot do supervisor e identidade de raiz sintética

**Estado:** protótipo experimental em Draft PR. **Não é isolamento, autenticação nem autorização.** Implementa apenas o PR-B proposto na [ADR-012](../adr/ADR-012-trusted-snapshot-boundaries.md) (seções 7.1 e 7.2). Invariantes preservadas: `STRONG=UNAVAILABLE`, `readiness=BLOCKED`, `agent_execution_authorized=false`, `file_operations_authorized=false`, `cloud_call_authorized=false`, `data_transfer_authorized=false`. A1 `NOT_VERIFIED`; A3 fora da garantia inicial; ABA sem mitigação completa. Auditorias independentes do Codex: 1ª (HEAD `38adf49`), 2ª (HEAD `669846e`, mais o complemento do relatório integral no HEAD `58c69d8`) e 3ª (HEAD `c302d07`) com findings corrigidos (seções "Correções após a primeira auditoria", "Correções após a segunda auditoria" e "Correções após a terceira auditoria"). **Quarta auditoria independente: PENDENTE.**

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
- CLI fechada `trusted_root.py --synthetic-only [--json]`: toda a sequência (fixture, âncora, abertura, observação, fechamento, remoção) fica sob tratamento de erro; falhas esperadas ou de infraestrutura viram um relatório `REFUSED` sanitizado (só códigos, sem caminhos nem traceback) com saída **2**; uso inválido continua 64. **Falhas de limpeza são observáveis**: `cleanup_failures` ∈ {`anchor_close`, `root_close`, `fixture_remove`}, e o resultado passa a `OBSERVED_WITH_CLEANUP_FAILURE` (nunca `IDENTITY_OBSERVED_NOT_AUTHORIZED`). A criação da fixture é atômica quanto ao resíduo: se `mkdir` ou a escrita do marcador falharem, a fixture parcial é removida e, se a remoção também falhar, `FixtureSetupError` carrega `fixture_remove`. A remoção (`_remove_fixture`) só atua em um diretório **registrado por `make_synthetic_fixture` nesta execução** (`_CREATED`: caminho → `(dev, ino)` lidos logo após o `mkdtemp`) e cuja identidade ainda confere; **identidade ausente nunca prova posse**: se o `lstat` inicial falhar, a criação é recusada, nada é removido (nem recursivamente) e `fixture_remove` é declarado em `cleanup_failures`; prefixo do nome, local temporário e ausência de symlink são verificações adicionais e **não provam** que a execução criou o diretório. Qualquer outro caminho é recusado sem tocar em nada. Toda etapa de limpeza trata `Exception`: o relatório só ganha o código fixo (`root_close`, `anchor_close`, `fixture_remove`), nunca `str(exceção)`, e uma etapa que falha não impede as seguintes. A defesa contra troca do diretório por outro processo do mesmo UID (A3) segue fora da garantia.
- `check_root_report` aplica um **esquema estrito**: conjunto exato de chaves, `schema == trusted-root-diagnostic/1`, invariantes com tipos exatos, `synthetic_only=true`, os cinco campos negativos (`owner_*`, `aba_protection_proven`, `external_writers_excluded`, `anchor_provenance_verified`) explicitamente `false`, identidade completa e tipada (`dev`, `ino`, `mnt_id`, variante, `mnt_ns` no formato `mnt:[N]`, máscara com os bits exigidos) e `identity_scope=comparison_only` em resultados não recusados, `reason` de um conjunto fixo (`ROOT_REASONS` ou `infrastructure_<ERRNO>`) em `REFUSED`, códigos de limpeza ordenados e sem repetição, e coerência entre `result`, `reason`, `identity` e `cleanup_failures`. **Validar o esquema não prova autenticidade nem proveniência**: um relatório forjado e coerente passa.

**`supervisor_boot`**:
- `collect_inventory()`: lê `/proc/self/fd` em processo monothread (`close_range` **não** é usado) e **confronta a listagem com uma sondagem independente** (`fcntl(F_GETFD)` em `0..RLIMIT_NOFILE`, recusada acima de 2^20): FD sondado ausente da listagem, ou mais de um número listado que não existe mais (o da própria listagem), ou descrição instável entre duas leituras, tornam o inventário inconsistente. Identidade do procfs: `readlink /proc/self` e `/proc/self/stat` precisam coincidir com o pid. Um FD sentinela `/dev/null` aberto na coleta deve reaparecer com a identidade esperada. Uma segunda listagem precisa coincidir com a primeira dentro do intervalo sondado. Alvos que são caminhos de arquivo são redigidos.
- **Validação semântica do inventário** (`_validate_inventory`): além dos tipos, exige `probe_range` em [3, 2^20], FDs estritamente crescentes (sem duplicata) e dentro do intervalo sondado, `access` e `opath` coerentes com `flags`, `transient == 1` quando `probe_agrees`, e `sentinel_verified` quando `structurally_consistent`. Combinações contraditórias → `inventory_contradictory`; sucesso não declarado → `inventory_inconsistent`; forma inválida → `inventory_malformed`. `target` é validado por **recusa** contra um formato fechado **e coerente com o `kind`**: `fifo`↔`pipe:[N]`, `socket`↔`socket:[N]`, `chr_devnull`↔`/dev/null`, `tty`↔`<tty>`, `anon_inode`↔`anon_inode:[nome]` ou `anon_inode:nome` (colchetes balanceados) e `<redacted-path>` (genérico) para qualquer `kind`. Formato desconhecido (caminhos, `pipe:/caminho`, `anon_inode:[x` sem fechar) dá `inventory_target_invalid`; formato válido de OUTRO `kind` (`regular` com `pipe:[1]`) dá `inventory_contradictory`; o texto recusado nunca é reproduzido. A coleta real usa a mesma tabela (`_safe_target(target, kind)` redige o que não casa) e classifica `anon_inode` antes do tipo do `stat` (o kernel dá a esses inodes modo regular). **Passar nessa validação não dá proveniência**: um dicionário recebido de fora continua dado não confiável; o relatório registra `inventory_provenance` (`collected_in_process`, `caller_supplied_unverified` ou `none`).
- **Três conceitos distintos.** (1) *Inventário estruturalmente consistente*: listagem, sondagem e metadados concordam nesta observação (`inventory_structurally_consistent`). (2) *Inventário efetivamente completo*: **não comprovável** (corridas, `/proc` adulterado de forma coerente com a sondagem); o relatório afirma sempre `inventory_effectively_complete=false`. (3) *Ausência de capacidades não observadas*: **não comprovada**; `unobserved_capabilities_excluded=false`. `CLEAN_FOR_GRANTS` significa apenas "nenhum FD observado é desconhecido".
- `CapabilityRegistry`: **não há API de declaração.** Não existe método que aceite um FD já existente: `place_devnull(0|1|2)` e `make_pipe()` criam o FD, ancoram e só então emitem o grant (`_issue` recusa tudo que não seja um recibo criado por essas fábricas — inclusive um `int`, um `Grant` montado à mão ou um recibo forjado: `declaration_refused`). `grants` é uma visão somente leitura, a classe usa `__slots__`, a avaliação aceita apenas o tipo exato `CapabilityRegistry`, só confia em grants que **este** registro emitiu e revalida cada um (tipos, `kind`, âncoras distintas). `_MINT`, `_mint_grant`, `_registry_with` e `_record` **não existem** no módulo de produção; os testes puros montam registros sintéticos com um helper local que escreve no estado privado (o que código no mesmo processo sempre poderia fazer). **Limite explícito:** isto fecha o caminho de concessão por declaração da interface operacional; não é fronteira contra código Python arbitrário no mesmo processo (A3, fora da garantia).
- **Ciclo de vida do registro.** `close()` (idempotente; também como gerenciador de contexto) fecha as âncoras privadas, esvazia os grants e invalida o registro: a avaliação recusa `registry_closed` e as fábricas também. Os FDs entregues ao chamador (pipes, slots 0-2) não são fechados. **Posse de FDs (P2-01):** cada FD e cada âncora tem um único dono por vez — uma lista local da chamada durante a fábrica, depois `_owned` do registro — e sai da lista **antes** de ser fechado; nada é fechado duas vezes nem se tenta fechar de novo, de modo que um número reaproveitado por outro FD entre dois closes nunca é fechado por engano. `_issue` é transacional (constrói o `Grant`, depois `_issued`, `_owned` e `_grants`, desfazendo o que tocou em qualquer falha) e nunca fecha a âncora do recibo. `make_pipe` é tudo-ou-nada (qualquer falha revoga um primeiro grant já emitido, fecha os dois FDs e as âncoras uma única vez, remove os recibos pendentes e não deixa grant). Se `place_devnull` falhar depois do `dup2`, o slot permanece como `/dev/null` herdável **sem grant** (a autoridade herdada anterior já foi descartada e não é restaurável); se o slot estava fechado e foi reutilizado, volta a ficar fechado. Nenhum caminho deixa FD vazado, grant parcial, recibo pendente nem âncora órfã (o resíduo documentado de `place_devnull` após o `dup2` é a única exceção). Número de FD reutilizado após `close` é detectado por identidade/OFD.
- **Direitos, não só identidade.** Cada `Grant` guarda `kind`, `dev`, `ino`, `flags` completos (`F_GETFL`: modo de acesso, `O_PATH`, `O_APPEND`...), estado `inheritable` (↔ `FD_CLOEXEC`) e um **dup privado (âncora, FD ≥ 3, CLOEXEC)** da mesma open file description. A classificação compara tudo estritamente e usa `kcmp(KCMP_FILE)` entre o FD e a âncora para detectar troca de open file description (inclusive reabertura do mesmo inode). Se `kcmp` não puder ser executado, o grant é `unknown` (`ofd_unverifiable`), nunca autorizado por falta de informação. As âncoras aparecem no inventário e são contabilizadas como `registry_anchor` (e viram `unknown` se perderem CLOEXEC ou identidade).
- `place_devnull(0|1|2)`: abre um `/dev/null` **novo** (não duplica FD herdado), verifica `S_ISCHR` e `rdev==1:3`, trata explicitamente o caso em que `open()` reutiliza o número do slot fechado (onde `dup2(fd, fd)` não alteraria flags: chama `set_inheritable(True)`), valida o estado efetivo (`chr_devnull`, sem CLOEXEC, `rdwr`, sem `O_PATH`) e, se falhar, levanta `BootRefused` devolvendo fechado o slot que ela mesma abriu. Limite de confiança: o `/dev/null` do namespace atual; não protege contra quem controla `/dev`.
- `evaluate(inventário, registro)` valida o inventário (chaves e tipos exatos, sem duplicata, `kind` conhecido), classifica cada FD (inclusive 0, 1 e 2) como `authorized`/`unknown` com a lista `mismatch` dos atributos que divergiram (`identity`, `access`, `opath`, `flags`, `cloexec`, `ofd`, `ofd_unverifiable`). FD 0/1/2 fechado ou grant sem FD impedem veredito limpo. `diagnose(registro)` não aceita coletor injetável, nunca levanta e converte exceção/ausência/saída malformada em `REFUSED`.
- Relatórios: `_report` não aceita campos reservados (`ValueError`), compõe as invariantes a partir de `INVARIANTS` (visão somente leitura) e passa por `check_boot_report`, que chama `check_report` (tipos exatos: `strong`, `readiness`, as quatro autorizações; `bootstrap_trusted`, `bootstrap_complete`, `inventory_effectively_complete` e `unobserved_capabilities_excluded` = `false` quando presentes) e aplica um **esquema estrito**: chaves exatas por veredito, `schema`, textos fixos (`limitations`, `not_verified`, `inventory_source`), cada entrada validada pelo mesmo `_check_entry` do inventário mais `status`/`reason`/`mismatch` coerentes (razão autorizada ↔ `kind`, `cloexec`, `access` e FD permitidos; `mismatch` único e na ordem canônica), listas tipadas, ordenadas e sem repetição, relação `entries` ↔ `unknown_fds` ↔ `std_closed` ↔ `grants_missing` ↔ veredito, `inventory_provenance` `none` somente em `REFUSED` e `reason` de um conjunto fixo. **Validar o esquema não prova autenticidade nem proveniência**: um relatório forjado e coerente passa (`limitations` o declara). Vereditos: `CLEAN_FOR_GRANTS`, `UNKNOWN_CAPABILITIES`, `REFUSED`; **nenhum** significa bootstrap confiável. Campos fora do schema de um relatório não são adicionados artificialmente.
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
- `EAGAIN` do `openat2` (corrida de resolução; o man documenta o retorno quando a resolução não pôde ser concluída com segurança) vira `resolution_race`, distinto de `open_failed`: é recusa fail-closed, **sem retry** e com as flags de resolução inalteradas; nenhum FD é concedido e a CLI sai com 2.
- Arquiteturas: x86_64 e arm64; outras são recusadas. Falta de syscall (ENOSYS/EPERM/EINVAL) recusa, sem fallback.

## Casos de recusa cobertos

Plataforma/arquitetura não suportada; syscall ausente; âncora ou FD inválido/fechado; arquivo regular no lugar do diretório; symlink no lugar da raiz ou do marcador; raiz renomeada/substituída/removida; identidade divergente; campo obrigatório de `statx` ausente; sem identificador de montagem; `ino`/`dev` inconsistentes; observação instável; mountpoint (simulado e `/proc` real); inventário inconsistente (FD real omitido, transitório falso, instável), malformado ou com falha de syscall; procfs/pid divergente; processo multithread; `RLIMIT_NOFILE` ilimitado; capability de tipo não prevista; registro forjado; FD extra herdado; objeto sensível em 0/1/2; grant trocado por outro objeto (extremo de pipe, mesmo inode reaberto); `/dev/null` que não é 1:3; falhas de infraestrutura e de limpeza da CLI.

## Testes e condições

A classificação é **por classe de teste**; cada teste está em exatamente uma categoria e o total não duplica contagens. "Real" significa que o comportamento vem do kernel; em "misto" a preparação/controle usa syscalls reais, mas o finding principal depende de uma falha injetada (mock) e, portanto, **não** prova o kernel.

| Categoria | `test_trusted_root` | `test_supervisor_boot` | Total | O que prova |
|---|---|---|---|---|
| Kernel/sistema de arquivos reais, no processo, sem mocks (`KernelTests`, `CleanupRealTests`) | 18 | 0 | 18 | openat2/statx reais e remoção segura de fixtures |
| Subprocesso real, sem mocks (`CliSubprocessTests`, `ChildProcessTests`) | 2 | 16 | 18 | `/proc/self/fd`, fcntl, kcmp, objetos reais do kernel, fábricas e CLI em filhos descartáveis |
| Misto: real + falha injetada (`MixedTests`, `CliFaultInjectionTests`, `ChildMixedTests`, `ChildFaultTests`) | 31 | 13 | 44 | lógica do programa sob falha (rollback, posse de FDs, limpeza); não o kernel |
| Lógica pura / dados sintéticos (`PureMockTests`, `PureLogicTests`) | 7 | 30 | 37 | lógica do programa |
| **Total** | **58** | **59** | **117** | |

Os testes que alteram FDs (dup2, close, pipes, herança) rodam **apenas** em subprocessos `python -I` descartáveis; o processo do operador e o terminal nunca são alterados. Timeout ou saída malformada do filho falha o teste. Um `skip` por syscall indisponível (ex.: `kcmp`) não é evidência positiva.

### Resultados por ambiente

| Ambiente | Execução | Resultado |
|---|---|---|
| Container do desenvolvimento (Linux 6.18, Python 3.13, x86_64), HEAD desta rodada | 117 testes dos dois módulos; suíte `integrations/isolation` 478 (361 anteriores + 117); `tests/` 188; skips: 0; `-W error` sem `ResourceWarning` | todos OK |
| Arch Linux do proprietário (ext4, kernel 7.2.4), informado por Arthur, **no HEAD `c302d07`** | 458 testes de isolamento, 188 gerais, as duas CLIs `--synthetic-only` | OK; CLIs com código 2 e todas as autorizações `false`; único aviso: `ResourceWarning` em `test_supervisor_boot.py:832` (corrigido nesta rodada). **Anterior às correções desta rodada: precisa ser revalidado.** Não comprova isolamento operacional |

Nenhum resultado do container é apresentado como execução no Arch. Os 478 testes de isolamento do HEAD atual **ainda não foram executados no Arch**.

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

### Complemento da leitura integral da segunda auditoria

Estes dois pontos só apareceram quando o relatório integral da segunda auditoria (HEAD `669846e`) foi lido; não constavam do resumo usado na rodada anterior.

| Ponto | Problema | Correção | Evidência |
|---|---|---|---|
| P2-02 | `_validate_inventory()` aceitava `target="/private/path"` (só checava o tipo `str`); o caminho seguia `evaluate` → `_validate_inventory` → `_evaluate` → relatório | `target` só passa se casar com o formato fechado; valores iniciados por `pipe:`, `socket:` ou `anon_inode:` não são presumidos seguros; recusa `inventory_target_invalid` (sem reescrever); `inventory_provenance` continua `caller_supplied_unverified` | negativos: `/private/path`, `pipe:/private/path`, caminho pessoal fictício, `pipe:[1]/x`, `pipe:[abc]`, quebra de linha, NUL, 40 caracteres, vazio; tipos inválidos (`None`, `int`, `bytes`, `list`) ⇒ `inventory_malformed`; controles positivos: 7 alvos legítimos/sanitizados reproduzidos sem alteração |
| P3-01 | `errno.EAGAIN` caía em `open_failed` | `_OPEN_ERRORS[EAGAIN] = "resolution_race"`; sem retry, flags de resolução inalteradas | falha injetada: `resolution_race`, uma chamada por tentativa, nenhum FD novo, CLI com `file_operations_authorized=false` e saída 2; controle de resolução normal preservado |

Mutações verificadas: remover o mapeamento de `EAGAIN` e desligar a checagem de `target` fazem os testes falharem.

## Correções após a terceira auditoria

Terceira auditoria Codex sobre o HEAD `c302d07160dbc854dd30896a4c1194b2bfae7c73`: três P2, dois P3 e um `ResourceWarning` (informado pelo proprietário no Arch). Escopo: apenas os cinco arquivos autorizados.

| Ponto | Problema | Correção | Evidência |
|---|---|---|---|
| P2-01 | Rollback não transacional: âncora vazada se `_Created` falhava, âncora do primeiro grant fechada duas vezes quando o segundo `_issue` falhava (número reaproveitado entre os dois closes podia fechar outro FD), grant residual com âncora fechada se `_issued.add` falhava | posse única de FDs/âncoras (lista local da chamada → `_owned` do registro), saída da posse **antes** do close, sem nova tentativa; `_issue` transacional; `make_pipe` revoga o primeiro grant se o segundo falha; `close()` idempotente; recibo com flag `used`; `_drop_pending` | `ChildFaultTests`: 14 pontos de falha em `make_pipe` e 7 em `place_devnull` (primeira/segunda âncora, construtor de `_Created`, `_pending.append`, construtor de `Grant`, inserção em `_grants`, `_issued.add`, `_owned.add`, falha após o primeiro `_issue`), cada um em subprocesso real com conjunto de FDs abertos idêntico ao anterior, estado do registro zerado e fábrica reutilizável; interposição de um FD novo no número recém-fechado após **cada** `close` (nenhum número fechado duas vezes, FDs interpostos permanecem abertos); `close()` repetido; registro fechado ⇒ `registry_closed` |
| P2-02 | `check_boot_report` aceitava `fd="not-an-int"`, `status="authorized"`, `inventory_provenance="none"` e `target="/private/path"` em `CLEAN_FOR_GRANTS`; `check_root_report` aceitava `schema="wrong"` sem identidade nem campos negativos | esquemas estritos (ver Contratos) reutilizando `_check_entry`; `ROOT_REASONS`/`_REFUSAL_REASONS` fixos; **sem alegar autenticidade** | `test_fabricated_boot_reports_are_refused_field_by_field` e `test_root_report_schema_is_strict_per_field`: cada campo adulterado isoladamente (ausente, tipo errado, texto sensível, contradição) |
| P2-03 | `RuntimeError` na limpeza escapava com caminho privado (`_remove_fixture` só tratava `OSError`) | `except Exception` em cada etapa (`_guarded`), códigos fixos, falhas múltiplas registradas, resultado `OBSERVED_WITH_CLEANUP_FAILURE` ou `REFUSED`, CLI com saída 2; `_refused_report` nunca reproduz texto arbitrário | `RuntimeError` em `OpenedRoot.close`, `os.close`, `shutil.rmtree`, em sequência, durante a criação da fixture, com mensagens de caminho fictício ausentes de stdout/stderr e relatório coerente |
| P3-01 | `kind="regular"` com `pipe:[1]` e `anon_inode:[eventpoll` desbalanceado eram aceitos | tabela `kind`↔`target`; `anon_inode` balanceado; `<redacted-path>` genérico; `_kind_of` classifica `anon_inode` antes do `stat`; vale no inventário e no relatório classificado | matriz positiva/negativa; coleta real de `epoll`, `socketpair`, `eventfd` e pipe produz inventário e relatório coerentes |
| P3-02 | A documentação afirmava que prefixo, local e não-symlink provavam que a fixture era da execução | afirmação **corrigida**: só o registro `_CREATED` com identidade `(dev, ino)` prova; A3 continua fora da garantia | diretório com nome/local/tipo corretos mas não criado pela execução é recusado; diretório substituído (outro inode ou symlink) é recusado e preservado |
| Aviso | `ResourceWarning` em `test_supervisor_boot.py:832` (três `TemporaryFile` não fechados) | `contextlib.ExitStack` no teste; nenhum código operacional alterado | `python3 -W error` sem avisos |

Mutações verificadas (os testes falham): fechar sem sair da posse antes; não remover recibo pendente; não desfazer `_issued` no rollback; não revogar o primeiro grant; fechar a âncora duas vezes em `_revoke`; ignorar `_check_classified`; aceitar `provenance="none"` fora de `REFUSED`; não validar `identity`; remover o registro `_CREATED`; limpeza só com `OSError`; remover a precedência de `anon_inode` em `_kind_of`. Contra o código do HEAD `c302d07`, os novos testes de falha injetada reproduzem o fechamento duplo (`closed_log` com o mesmo número duas vezes) e a âncora vazada.

**Risco residual:** a posse de FDs é uma convenção do módulo; código Python arbitrário no mesmo processo (A3) continua fora da garantia. O resíduo de `place_devnull` após `dup2` (slot `/dev/null` herdável sem grant) permanece documentado. Nenhuma autorização operacional foi criada.

## Correção preventiva de identidade da fixture

Pedido do proprietário sobre o HEAD `1b5b430`: `make_synthetic_fixture()` registrava `_CREATED[parent] = None` quando o `lstat` inicial falhava e `_owned_now()` aceitava `ident is None`, dispensando a comparação de identidade. Agora a identidade ausente não é evidência: o registro não é criado, a operação é recusada com código sanitizado (`infrastructure_<ERRNO>` ou `unexpected_failure`), `rmtree` não é chamado e `fixture_remove` fica em `cleanup_failures` (o diretório recém-criado, sem identidade provada, permanece e é declarado). Contratos `REFUSED`, `OBSERVED_WITH_CLEANUP_FAILURE` e saída 2 preservados. A identidade local registrada **não** é proveniência confiável de uma raiz real (continua não comprovada). Testes: `OSError` e falha inesperada no `lstat` inicial; identidade ausente ou errada ⇒ `_owned_now() == False` e nenhuma remoção; fixture normal criada e removida; fixture substituída por outro inode recusada (já existente); nada sensível em stdout/stderr. **Quarta auditoria independente: PENDENTE.**

## Resultados não verificados

Execução dos 478 testes de isolamento no Arch/ext4/kernel 7.2.4, completude real de inventário (impossível de provar), `kcmp` bloqueado por seccomp/sandbox (resulta em `unknown`), raiz sob mount real do projeto, bind mounts, namespace diferente, `STATX_MNT_ID_UNIQUE` em kernel < 6.8 (caminho `legacy` só exercitado com mock), WSL2, macOS, comportamento no kernel 7.2.4/ext4 do proprietário, execução em terminal interativo real, SRT com FDs preexistentes.

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

Verificar a quarta rodada: posse única e fechamento único de FDs/âncoras em todos os caminhos de falha das fábricas e de `close()`, transacionalidade de `_issue`, esquemas estritos de `check_boot_report`/`check_root_report`, coerência `kind`↔`target`, limpeza sob exceções inesperadas e registro de posse da fixture; ausência de qualquer caminho de concessão por declaração; verificar se algum caminho transforma `CLEAN_FOR_GRANTS` ou `IDENTITY_OBSERVED_NOT_AUTHORIZED` em autorização; se `place_devnull` pode propagar autoridade herdada; completude do inventário sob threads e corridas; mapeamento de errno do `openat2`; reexecutar no Arch/ext4/7.2.4.
