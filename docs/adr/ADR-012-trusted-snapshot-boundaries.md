# ADR-012 — Fronteiras de confiança para snapshot e supervisor (GH-F1.18)

**Status:** proposta, **somente documental** (PR-A da GH-F1.18; 25/10/2026; revisada após a primeira auditoria Codex, ver seção 16). Esta ADR registra decisões arquiteturais propostas para uma arquitetura **experimental**. Nada aqui está implementado. `STRONG=UNAVAILABLE` e `readiness=BLOCKED` permanecem invariantes; nenhuma flag de autorização muda (`agent_execution_authorized`, `file_operations_authorized`, `cloud_call_authorized`, `data_transfer_authorized` seguem `false`). **A aprovação desta ADR não desbloqueia a execução de agentes.** A auditoria independente do Codex sobre o HEAD corrigido está **pendente**. Os componentes das seções 6, 7, 9 e 11 são propostas, não funcionalidades.

## 0. Vocabulário de evidência

Para evitar que objetivos sejam lidos como garantias, esta ADR usa quatro níveis, sempre nesta ordem de força:

| Nível | Significado | Exemplo |
|---|---|---|
| **Objetivo arquitetural** | Propriedade que a arquitetura pretende alcançar. Não implica que exista ou funcione. | "a célula não alcança a origem" |
| **Propriedade testável** | Objetivo formulado de modo que um teste positivo e um negativo possam refutá-lo. | "leitura da origem a partir da célula falha com controle positivo no mesmo run" |
| **Evidência experimental** | Resultado de testes executados em condições declaradas (execuções, kernel, filesystem, carga), com resíduos desconhecidos. | os canários sintéticos da GH-F1.13 a F1.17 |
| **Garantia demonstrada** | Propriedade com prova correspondente e revisada. | **Nenhuma** é afirmada por esta ADR |

Todo objetivo desta ADR é **`NOT_VERIFIED` até implementação, inventário de capacidades e testes positivos e negativos**. SRT e bubblewrap, isoladamente, não constituem comprovação de isolamento integral.

## 1. Contexto e motivação

A GH-F1.13 a F1.17 produziram, em fixtures sintéticas, evidências experimentais e limites que esta ADR consolida:

| Fase | Resultado registrado | Limite |
|---|---|---|
| GH-F1.13 | `NATIVE_HARDLINK_LEAK_REPRODUCED`: Read/Edit nativos e `open()` arbitrário ignoram `pathguard`/`openat2` | guardas são voluntários, em processo |
| GH-F1.14 | Snapshot sintético de um arquivo, por cópia de bytes (inode novo, `nlink==1`), lido sob SRT | um arquivo fictício; sem proveniência da raiz |
| GH-F1.15 | Segunda leitura detecta mutação in-place de mesmo tamanho nos 5 interleavings cooperativos | não prova ausência de ABA |
| GH-F1.16 | `ABA_UNDETECTED` reproduzido; `root_fd` antigo continua lendo árvore substituída | detecção comparava `(dev, ino, size)` e bytes |
| GH-F1.17 | Freeze cooperativo por `flock` funciona com escritor cooperativo; `ADVISORY_BYPASS_REPRODUCED` com escritor não cooperativo | `flock` é advisory |

Causa comum: o toolkit tenta obter, por verificações dentro de um processo que **compartilha UID** com os demais escritores, propriedades que só poderiam vir de uma fronteira construída pelo kernel em volta dos agentes ou de uma primitiva de captura atômica. Mais leituras ou hashes reduzem janelas, mas não as fecham.

**Ambiente informado pelo proprietário (25/10/2026), não comprovado como capacidade de segurança:** `findmnt -T /home/arthur/Projetos -no FSTYPE` → `ext4`; `stat -f -c '%T'` → `ext2/ext3` (nome que o `stat` usa para a família ext); `uname -r` → `7.2.4-arch1-2`. Isto descreve o ambiente do MVP e **não** estabelece que reflink, snapshot atômico de árvore ou fs-verity estejam disponíveis: tais capacidades dependem do sistema de arquivos e das opções efetivas e devem ser verificadas por teste. Nenhuma suposição sobre o sistema de arquivos de outras máquinas é feita a partir do checkout em nuvem.

## 2. Objetivo de segurança do Toolkit

Estabelecer, de forma verificável e reutilizável entre projetos, uma fronteira entre: (1) a pasta explicitamente autorizada pelo proprietário; (2) um supervisor confiável; (3) a preparação de snapshots independentes; (4) a célula de execução isolada dos agentes; (5) a futura aplicação de alterações, mediante aprovação humana. A fronteira não pode depender apenas de instruções em prompts, locks voluntários ou verificações de caminho.

Objetivos arquiteturais (todos `NOT_VERIFIED`): **(i)** impedir que processos sob controle do supervisor alcancem dados fora da pasta autorizada, **(ii)** aumentar a coerência do que o agente lê e recusar quando houver evidência de instabilidade, **(iii)** condicionar a integridade do que é aplicado de volta à revisão humana. Não é objetivo proteger o projeto contra outro processo malicioso do mesmo usuário.

## 3. Modelo de ameaças

| Classe | Descrição | Tratamento proposto |
|---|---|---|
| **A1** | Agentes e subprocessos sob controle do supervisor (incluindo ferramentas e hooks que o supervisor lançar) | Principal fronteira a isolar. **Objetivo arquitetural; `NOT_VERIFIED` até implementação, inventário de capacidades e testes positivos e negativos** |
| **A2** | Escritores honestos concorrentes (editor, git, bundler, watchers, gerenciadores de pacote que criam hardlinks) | Observação, detecção e **recusa**, com resíduo; causam inconsistência, não malícia |
| **A3** | Escritor malicioso do mesmo UID, fora da célula | **Fora da garantia inicial** (ver 3.1) |
| **A4** | root, kernel comprometido, hardware não confiável | Fora do escopo |

### 3.1 Alcance real de A3

Um A3 não ameaça apenas a pasta de origem. Sem fronteira adicional, pode comprometer, em princípio, **todos** os artefatos que residem no contexto do mesmo usuário:

- o código do toolkit e a configuração;
- o supervisor (inclusive por ptrace ou `/proc` quando as verificações do kernel permitirem);
- o Snapshot Store e os manifestos;
- logs e evidências;
- a interface e o registro de aprovação;
- o Apply Gate.

Por isso **esta ADR não promete confidencialidade, integridade, disponibilidade nem autenticidade contra A3**, e nenhuma flag de evidência pode sugerir o contrário. Medidas como `PR_SET_DUMPABLE=0` são **hardening limitado**: segundo a documentação, essa chamada define o atributo "dumpable", que controla a geração de core dumps, impede `PTRACE_ATTACH` por processos sem privilégio equivalente e altera a propriedade dos arquivos em `/proc/<pid>`; é revertida em certas transições de credenciais ou `execve`. Ela **não** é isolamento de filesystem e não impede um A3 de modificar arquivos que o mesmo UID pode escrever.

Fundamentos documentais (consultados em 25/10/2026, seção 15):
- Processos do mesmo UID geralmente passam nas verificações de ptrace (UID igual, dumpable, capacidades equivalentes); o Yama limita *attach* conforme `ptrace_scope` (ptrace(2)).
- O UID que cria um user namespace tem todas as capacidades nele, processos do namespace pai com esse UID não são excluídos dele, e criar user namespace pode enfraquecer o Yama (user_namespaces(7), ptrace(2)). Logo bubblewrap, SRT e mount namespaces restringem quem está **dentro**; não é demonstrado que protejam o conteúdo contra o mesmo usuário **fora**.
- Landlock restringe o próprio processo e seus descendentes, não outros processos (landlock(7)).
- fs-verity impede escrita e truncamento de arquivos regulares verity, mas metadados continuam alteráveis, diretórios não são cobertos e a autenticidade do digest exige esquema próprio (documentação do kernel).

## 4. Fronteiras de confiança

```text
Proprietário (confirmação interativa)   ← confiança humana
   → Supervisor                         ← confia no kernel, no Python do sistema, no código revisado do toolkit e no humano
   → Captura controlada                 ← lê a origem como dado não confiável; não executa nada dela
   → Snapshot Store                     ← dado selado e reverificável; não é imutável contra A3
   → Célula isolada (SRT/bwrap, ...)    ← A1; objetivo: sem rede e sem acesso à origem (NOT_VERIFIED)
   → ChangeSet                          ← dado fechado; nunca patch executável
   → Apply Gate                         ← processo separado; único caminho de escrita na origem, com aprovação humana
```

Objetivo: cada seta transporta **dados**, nunca capacidades (sem fds, caminhos vivos ou comandos); isso é um requisito a testar, não um fato. O supervisor não confia em: conteúdo da pasta, nomes, symlinks, `.git` e configurações internas, saída da célula, JSON produzido por qualquer agente. A identidade de uma pasta (seção 7.2) **não** equivale a autorização autenticada nem exclui escritores do mesmo UID.

## 5. Arquiteturas candidatas e comparação

Células usam os níveis da seção 0. "NV" = `NOT_VERIFIED`.

| ID | Arquitetura | A1 | A2 | A3 | Privilégio | Principais limitações |
|---|---|---|---|---|---|---|
| C0 | Status quo (pathguard, openat2, flock cooperativo) | não | parcial (evidência experimental) | não | não | guarda voluntário; ABA; `flock` advisory |
| **C1** | Supervisor + captura com detecção + store privado + célula SRT somente leitura | objetivo, NV | detecção com resíduo, NV | não | não | resolução de timestamps, eventos não observados, sem atomicidade |
| C2 | C1 + backend de cópia atômica do filesystem | idem | atômico apenas onde o FS comprovadamente suporta | não | a verificar | `FICLONE` é por arquivo; snapshot de árvore depende do FS; indisponibilidade presumida em ext4 até verificação |
| C3 | C1 + fs-verity no store | idem | detecta | parcial (conteúdo de arquivos regulares do store) | a verificar | exige FS com recurso habilitado; não cobre diretórios; metadados mutáveis |
| C4 | C1 + Landlock dentro da célula | segunda camada, NV | detecta | não | não | autorrestritivo; fds já abertos não são restringidos; cobertura parcial de operações |
| C5a | **UID distinto** com custódia e permissões verificadas | possível, NV | possível, NV | **condicional, NV** | sim (contas) | viola a restrição atual de "sem contas adicionais"; só vale se custódia de credenciais, diretórios, `/proc` e canais IPC for verificada |
| C5b | **Containers / namespaces rootless** | possível, NV | possível, NV | **não protege por si só** | não | o dono do namespace mantém poder sobre ele (seção 3.1); container no mesmo UID não protege contra A3 |
| C5c | **Máquina virtual** | possível, NV | possível, NV | **condicional, NV** | sim | depende dos limites reais de acesso ao host e do armazenamento compartilhado (pastas montadas no guest reabrem o acesso) |
| C6 | memfd selado como armazenamento | não é isolamento | não é captura atômica | conteúdo do blob em memória | não | imutabilidade de um blob, não isolamento de processos nem captura atômica (seção 8.4) |
| C7 | FUSE supervisionado | possível, NV | n/a | não | helper setuid | dependência pesada |

**C5 não é uma única opção.** Nenhuma das variantes C5a a C5c protege automaticamente contra A3: a proteção contra A3 permanece **condicional e `NOT_VERIFIED`** até que os limites efetivos de confiança (propriedade e permissões do store, canais de comunicação, mounts compartilhados, privilégios do processo supervisor) sejam descritos e comprovados por teste. Em particular, um container ou namespace rootless executado pelo mesmo UID **não** protege contra um escritor malicioso externo do mesmo UID.

C2, C3, C4 e C6 são **alternativas opcionais**, cada uma com propriedades e limitações próprias, e só podem ser adotadas após sonda de capacidade efetiva no ambiente e nova decisão.

## 6. Arquitetura selecionada e justificativa

**C1** como base, com C2 a C4 e C6 como camadas opcionais condicionais. Justificativa: não exige privilégio, conta adicional ou Docker; formula A1 como propriedade testável; reaproveita `pathguard`, `linux_openat2_guard`, `srt_launcher` e os pilotos existentes; é explícita sobre A3; e desloca a integridade final para o Apply Gate com aprovação humana vinculada a digest.

Esta arquitetura **não elimina ABA**, **não demonstra isolamento** e **não habilita STRONG**. Ela propõe detectar a classe comum de instabilidade, recusar quando houver indícios, medir e declarar o resíduo.

## 7. Contratos conceituais dos componentes (propostas, nada implementado)

### 7.1 Supervisor: protocolo de bootstrap (futuro)

Estado atual: nenhuma dessas etapas existe no código. A premissa de que apenas descritores acima de 2 seriam perigosos é **incorreta**: os descritores 0, 1 e 2 também podem referenciar capacidades sensíveis (sockets, arquivos, diretórios, terminais, pipes de outros processos). Protocolo proposto, a implementar e testar:

1. **Processo inicial monothread**, antes de iniciar threads, importar módulos de terceiros ou abrir recursos; executado com Python em modo isolado (`-I`).
2. **Inventário de todos os fds herdados** (incluindo 0–2) a partir de uma fonte verificada (por exemplo `/proc/self/fd` ou `close_range`), registrando tipo, destino e flags; qualquer entrada não prevista pela allowlist é recusada ou fechada.
3. **Validação ou substituição segura de stdin/stdout/stderr:** verificar que cada um é um terminal, pipe ou arquivo esperado e não um diretório, socket ou objeto inesperado; quando não for, substituir por descritores abertos pelo próprio supervisor (por exemplo `/dev/null`) antes de qualquer outro passo.
4. **Fechamento dos descritores não autorizados** e uso de `CLOEXEC` por padrão em tudo que o supervisor abrir.
5. **Allowlist explícita por processo filho:** cada filho recebe somente os fds nomeados para ele; nenhuma herança implícita.
6. **Canais IPC e recebimento posterior de fds:** o supervisor não aceita fds nem números de fd por argumento, ambiente ou arquivo; passagem posterior de descritores (por exemplo `SCM_RIGHTS`) só por canal explicitamente criado, com tipo e destino verificados no recebimento.
7. **Limitações conhecidas:** SRT e Landlock **não restringem descritores já abertos** antes da aplicação da restrição (Landlock: "files opened before sandboxing are not restricted"; direitos ficam associados ao fd e permanecem se o fd é repassado); portanto o inventário e o fechamento precisam ocorrer **antes** de lançar a célula. O comportamento do SRT com fds herdados não foi verificado.
8. Demais hardening: `PR_SET_NO_NEW_PRIVS` (irreversível, herdado por filhos e preservado em `execve`), recusa de `euid==0`. `PR_SET_DUMPABLE=0` é hardening limitado (seção 3.1).

### 7.2 Raiz confiável e identidade

O supervisor abre a pasta ele mesmo, a partir de `/`, componente a componente com `openat2` (`RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, `RESOLVE_NO_XDEV`; `RESOLVE_BENEATH` quando houver `dirfd` ancorado). Registra, **somente quando a máscara efetivamente retornada pelo `statx` (`stx_mask`) indicar que o campo foi preenchido**, `dev`, `ino` e identificador de montagem. Campos ausentes ⇒ identidade parcial declarada como tal, nunca preenchida por suposição.

**Identidade de montagem.** Distinguir:
- `STATX_MNT_ID` (Linux 5.8): identificador da montagem que contém o arquivo; coincide com o primeiro campo de `/proc/self/mountinfo` e com o retornado por `name_to_handle_at(2)`. A documentação não o descreve como único nem diz se pode ser reutilizado.
- `STATX_MNT_ID_UNIQUE` (Linux 6.8): identificador que a documentação diz "garantido de não ser reutilizado enquanto o sistema está em execução"; é o usado por `listmount(2)`/`statmount(2)`.
- A **máscara efetivamente retornada** pode diferir da solicitada; o campo só vale se o bit correspondente estiver ligado.
- A documentação consultada **não trata do escopo por mount namespace**; a validade de um identificador fora do namespace em que foi observado não é afirmada. Registrar também o namespace observado (por exemplo o link de `/proc/self/ns/mnt`) como contexto, sem tratá-lo como autenticação.

Esses campos ajudam a **comparar** o objeto e a montagem observados agora com os observados antes. **Não permitem recuperar ou autenticar um objeto histórico**, não autenticam o proprietário e não excluem escritores do mesmo UID. Por isso a reabertura é descrita como: *reabrir a pasta por caminho e comparar a identidade atual com a registrada*, e qualquer divergência, ou ausência de campo, resulta em recusa.

**`RESOLVE_NO_XDEV` e pontos de montagem.** A flag recusa qualquer travessia de ponto de montagem, **inclusive bind mounts legítimos**, com `EXDEV`; a documentação alerta que o uso amplo pode gerar erros espúrios em sistemas onde bind mounts são comuns (por exemplo uma pasta de projeto que contém um subdiretório montado, ou um caminho que passa por uma montagem). Decisão proposta: **manter a recusa por padrão** e documentar essa limitação como recusa legítima, não como defeito. Qualquer futura permissão para atravessar montagens exige âncoras explicitamente autorizadas pelo proprietário e verificação explícita (identidade da montagem, tipo de filesystem, destino); `NO_XDEV` **não será relaxado silenciosamente**.

### 7.3 Concessão do proprietário (futura)

Ver seção 9.

### 7.4 Captura controlada

Produz `SnapshotHandle` com identificador, digest do manifesto, nível de consistência e as evidências coletadas. Níveis possíveis: `DETECTED_STABLE` (nenhuma evidência de instabilidade observada; **não** é garantia), `ATOMIC_BACKEND` (somente quando backend atômico foi sondado e declarado) e `REFUSED_UNSTABLE`. Aceita apenas diretórios e **arquivos regulares**; arquivos regulares exigem `st_nlink == 1`. **Diretórios não estão sujeitos a `nlink==1`** (em muitos filesystems o `st_nlink` de um diretório reflete subdiretórios e não indica hardlink perigoso; o valor depende do filesystem). Copia bytes; nunca usa `link`, `rename` ou reflink da origem sem decisão específica.

### 7.5 Snapshot Store

- **Criação de diretórios:** `mkdirat` sob um diretório pai confiável (aberto e validado pelo supervisor, sem symlinks nos componentes), seguido de **abertura do diretório criado com `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` e validação** (tipo, dono, modo, `dev`/`ino`) antes de qualquer uso. A criação de diretório não usa `O_EXCL` (flag de `open`, não de `mkdirat`); a exclusividade vem de `mkdirat` falhar com `EEXIST` quando o nome existe.
- **Criação de arquivos regulares:** `openat` com `O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC` (e modo restritivo), nunca reutilizando nomes existentes; depois `fstat` para conferir tipo regular e `st_nlink == 1`.
- Manifesto com digest, selo e `verify` reexecutável no lançamento e ao final da célula. `chmod` e um digest isolado **não** são prova de imutabilidade contra A3: servem como convenção contra A1/A2 e como evidência de adulteração, com resíduo declarado.

### 7.6 Célula isolada

Extensão futura de `srt_launcher`: vê somente a cópia do store, por montagem somente leitura, mais área de trabalho separada; objetivo: sem rede e sem acesso à origem. `NOT_VERIFIED`: depende de inventário de capacidades (versões de SRT 0.0.81 e bubblewrap 0.12.0, seccomp, user namespaces) e de testes positivos e negativos em cada ambiente.

### 7.7 ChangeSet

Esquema fechado `{op, path, base_digest, new_digest}` + blobs; proibidos por padrão symlink, hardlink, dispositivos, mudança de modo além do bit executável e caminhos protegidos (`.git/**`, `.claude/**`, `.mcp.json`, rc de shell, definições de CI).

### 7.8 Apply Gate

Processo separado, sem agente; exibe o diff; exige aprovação humana vinculada a `hash(changeset, manifesto-base, identidade atual comparada)` com expiração e sem reutilização. A aplicação **não** forma, em geral, uma operação *compare-and-swap* atômica: comparar `base_digest` e depois executar `rename` são duas etapas separadas, com janela entre elas. `renameat2` documenta apenas operações de nomes: `RENAME_NOREPLACE` falha se o destino já existe e `RENAME_EXCHANGE` troca nomes de forma atômica; nenhum deles verifica conteúdo esperado. Tratamento por tipo de operação:

| Operação | Mecanismo proposto | Garantia | Estado |
|---|---|---|---|
| **Criar arquivo novo** | arquivo temporário completo no mesmo diretório + `renameat2(RENAME_NOREPLACE)` | não substitui um destino que já exista no instante da chamada | `NOT_VERIFIED` até teste |
| **Atualizar arquivo existente** | comparar identidade/`base_digest`, escrever temporário, trocar | **sem exclusão de escritores, a atualização condicional não é atômica**: um escritor concorrente pode alterar o arquivo entre a comparação e a troca; `RENAME_NOREPLACE` não resolve este caso (o destino existe por definição) e `RENAME_EXCHANGE` só troca nomes | **`NOT_VERIFIED`; sem promessa de ausência de sobrescrita concorrente**; reduzir a janela e **detectar após o fato** (reverificar o conteúdo trocado, preservar o original para reversão) |
| **Remover** | verificar identidade, `unlinkat` | `unlinkat` não verifica conteúdo; pode remover versão diferente da revisada | `NOT_VERIFIED`; mesma ressalva |
| **Alterar permissões** | verificar identidade, `fchmodat` por fd | pode atingir objeto diferente do revisado se o nome foi trocado; usar fd aberto e verificado | `NOT_VERIFIED` |

O Apply Gate permanece **`NOT_VERIFIED` para qualquer operação que exija exclusão de escritores ou semântica transacional**, até existir mecanismo demonstrado (por exemplo exclusão de escritores por fronteira adicional ou um procedimento com prova). Em caso de divergência detectada, o resultado é conflito, nunca sobrescrita silenciosa. O Apply Gate também não executa `git` na origem do usuário (configuração, hooks e filtros do repositório podem executar código).

## 8. Limitações de detecção e atomicidade

### 8.1 Evidências de detecção, não garantias

`ctime`, `mtime`, inotify e releituras são **evidências de detecção** sujeitas a:
- resolução e granularidade dos timestamps (alterações dentro da mesma unidade de tempo podem ser indistinguíveis);
- concorrência entre a observação e a leitura;
- eventos não observados: segundo inotify(7), acessos e modificações via `mmap(2)`, `msync(2)` e `munmap(2)` **não são reportados**; mudanças remotas em sistemas de arquivos de rede não são capturadas; pseudo-filesystems não podem ser monitorados;
- overflow da fila (`IN_Q_OVERFLOW`, limitado por `max_queued_events`), limites `max_user_watches`/`max_user_instances`, observação **não recursiva** (subdiretório novo pode já conter arquivos antes de o watch ser instalado), correspondência racy de `IN_MOVED_FROM`/`IN_MOVED_TO`, coalescência de eventos idênticos e impossibilidade de identificar o autor do evento;
- limitações do filesystem e das opções de montagem.

Não se afirma que `ctime` elimina ou sempre detecta ABA. A hipótese de que `ctime` não é definível pelo usuário comum e por isso torna detectável um subconjunto de A→B→A feito por `write()`/`truncate()` **não foi verificada em documentação nesta rodada** e deve ser **medida** no ambiente (PR-C), reportada como resultado experimental com resíduos. Um hash descreve os bytes lidos, não a estabilidade entre leituras.

### 8.2 Atomicidade

`FICLONE` é atômico em relação a escritas concorrentes **por arquivo** e exige o mesmo filesystem e suporte a reflink; não constitui snapshot atômico da árvore inteira. Snapshot atômico de árvore depende de recurso específico do filesystem, cuja disponibilidade e permissões **não** são presumidas (o ext4 informado não garante nenhum dos dois). Nenhum recurso dependente de filesystem é recomendado sem verificação de compatibilidade e permissões no ambiente.

### 8.3 fs-verity

Protege conteúdo de arquivos regulares verity (não diretórios; metadados continuam mutáveis; exige recurso habilitado no FS; cópia perde o estado). Opcional; não verificado neste ambiente.

### 8.4 memfd selado

Imutabilidade de um **blob em memória** é uma propriedade distinta de isolamento de processos e de captura atômica da origem: um memfd selado não impede que a origem seja lida de forma inconsistente antes da cópia, não restringe o que um agente pode acessar e não forma árvore de diretórios para ferramentas nativas. **Não é garantia de A1/A2.** Condições para o sealing, segundo memfd_create(2) e fcntl(2):
- criar o descritor com `MFD_ALLOW_SEALING` (sem a flag, o conjunto inicial é `F_SEAL_SEAL` e nenhum outro selo pode ser adicionado); `MFD_CLOEXEC` para não herdar em `execve`;
- não haver mappings compartilhados **graváveis** incompatíveis: `F_SEAL_WRITE` falha com `EBUSY` se existirem; `F_SEAL_FUTURE_WRITE` (Linux 5.1) é alternativa que não bloqueia mappings gravíveis já existentes;
- aplicar `F_SEAL_WRITE`, `F_SEAL_GROW` e `F_SEAL_SHRINK` e, por fim, `F_SEAL_SEAL` (que impede novos selos);
- verificar o resultado com `F_GET_SEALS` (retorna máscara; `EINVAL` se o descritor não suporta selos). Selos se aplicam apenas a descritores de `memfd_create` com sealing habilitado.

Selos protegem o conteúdo enquanto o descritor existe; não protegem o processo que o contém contra A3, nem a confidencialidade. Opcional e não verificado neste ambiente. A opção `--ro-bind-data` do bubblewrap (aparece na documentação do v0.12.0) copia dados de um fd para um arquivo montado somente leitura; sua adequação a árvores e limites de tamanho não foi avaliada.

## 9. Política futura de concessão pelo proprietário

Proposta, a decidir antes do componente correspondente: concessão por confirmação interativa em terminal aberto pelo próprio supervisor, exibindo identidade atual da pasta, caminho resolvido, resumo do inventário e nonce, com validade limitada e vínculo à identidade comparada e ao digest. Sem terminal interativo, recusar. O arquivo TOML de configuração expressa **intenção**, não concessão. Esta confirmação é procedural: **não é prova criptográfica nem protege contra A3** (seção 3.1), pois o mesmo UID pode alterar a configuração, o registro e a interface. Mecanismos externos (polkit, FIDO2) dependem de decisão humana e de revisão de dependências.

## 10. Política futura de exclusões, limites e privacidade

Proposta: excluir por padrão `.git`, arquivos de segredo conhecidos (`.env*`, chaves, tokens), diretórios de dependências e artefatos de build; limites explícitos de tamanho, quantidade de arquivos, profundidade e comprimento de nomes; recusa de nomes problemáticos (NUL, quebras de linha, colisões Unicode ou de caixa); recusa de arquivos esparsos acima do limite; manifesto contendo apenas metadados e digests, sem conteúdo; nenhum dado copiado para provedores externos sem autorização explícita; logs sem conteúdo de arquivos. Qualquer exceção exige confirmação do proprietário.

## 11. Escada de propriedades experimentais

Nomes só podem ser usados com estes significados. Cada degrau é um **objetivo `NOT_VERIFIED`** até haver implementação e testes; nenhum equivale a `STRONG`:

- **P0** raiz identificada pelo supervisor (campos de identidade efetivamente disponíveis, comparados agora);
- **P1** captura recusada quando há evidência de instabilidade (detecção sujeita à seção 8);
- **P2** snapshot independente, arquivos regulares com `nlink==1`, selado e reverificável;
- **P3** objetivo: célula sem acesso à origem nem a store gravável (propriedade testável com controles positivo e negativo);
- **P4** changeset verificado com aprovação humana vinculada (sem promessa de atomicidade da aplicação, seção 7.8);
- **P5** (opcional) captura atômica, somente com backend sondado;
- **P6** (opcional) conteúdo do store protegido por mecanismo do filesystem.

## 12. Critérios verificáveis de aceite e recusa

**Aceite (por PR futuro):** cada propriedade tem teste negativo com controle positivo no mesmo run; ausência de resultado, exceção, timeout ou tipo malformado = `NOT_VERIFIED`; `SKIP` por kernel não conta como prova; execução no Arch reportada com HEAD exato; auditoria Codex read-only antes do merge; aprovação humana específica por PR.

**Resultados de corrida.** Um número finito de execuções sem falhas **não** constitui prova matemática de ausência de ABA. Todo relatório de corrida deve declarar: quantidade de execuções, condições (kernel, filesystem, opções de montagem, carga, estratégia do escritor), resultados observados (inclusive aceitações inconsistentes e recusas), limitações e resíduos desconhecidos. Resultados experimentais são distinguidos de garantias.

**Recusa:** kernel ou syscall necessária ausente; filesystem não suportado ou não verificado; qualquer fd não previsto na allowlist (inclusive 0–2); travessia de montagem não autorizada (`EXDEV`); campo de identidade ausente na máscara retornada; instabilidade observada além do limite de tentativas; inotify indisponível, com overflow ou sem cobertura de um diretório novo; arquivo regular com `nlink>1`; arquivo especial; store com permissões diferentes das esperadas; digest divergente no lançamento; qualquer relatório que afirme `aba_protection_proven`, `STRONG`, isolamento de escritores não cooperativos ou atomicidade da aplicação sem prova correspondente.

**Linguagem proibida até haver prova:** "elimina ABA", "isolado de escritores", "STRONG", "proveniência verificada contra adversário", "garantia por construção", "sem sobrescrita concorrente". Permitida: "objetivo", "detectado", "recusado se instável", "resíduo medido", "A3 fora da garantia", "NOT_VERIFIED".

## 13. Riscos conhecidos e requisitos não resolvidos

- A3 sem proteção, com alcance sobre toda a cadeia (seção 3.1); proteção por C5a/C5c condicional e não verificada, C5b insuficiente isoladamente.
- A1 é objetivo `NOT_VERIFIED`; SRT 0.0.81 (beta) e bubblewrap 0.12.0 não foram revalidados para as novas montagens; padrões de deny ignorados no Linux falham abertos (documentação do SRT); bubblewrap é ferramenta de construção cujo nível de proteção depende dos argumentos e do que é montado (README do bubblewrap).
- Descritores herdados: protocolo da seção 7.1 não implementado; comportamento do SRT com fds preexistentes não verificado.
- Apply Gate sem atomicidade para atualização, remoção e permissões (seção 7.8).
- Resíduo de ABA dentro da resolução de timestamps e para escritas não observáveis (`mmap`); não quantificado ainda.
- Capacidades do ext4 do ambiente (reflink, fs-verity, snapshots) **não verificadas**; WSL2, DrvFs, NFS, FUSE e overlay não avaliados.
- Escopo de mount namespace dos identificadores de montagem não documentado nas fontes consultadas.
- `--bind-fd` e `--ro-bind-fd` não constam da documentação do bubblewrap v0.12.0 consultada; `--ro-bind-data` consta. Landlock não exercitado neste ambiente.
- Proveniência de `root_fd`, bind mounts reais e worktrees reais seguem `NOT_TESTED`.
- Auditoria independente do Codex sobre o HEAD corrigido pendente.
- Política de exclusões e fonte ativa dependem de decisão humana.

## 14. Relação entre PR-A, PR-B, PR-C, PR-D e GH-F1.19+

- **PR-A (esta ADR):** documentação; nenhum código, teste, flag ou política alterada.
- **PR-B (proposto, não iniciado):** protocolo de bootstrap do supervisor e abertura confiável da raiz, com testes em fixtures.
- **PR-C (proposto):** harness de medição das evidências de detecção, sem novo guard e sem reivindicar garantia.
- **PR-D (proposto):** captura e store, com recusa, somente em fixtures.
- **GH-F1.19+ (proposto):** concessão interativa, célula com montagem somente leitura e Landlock opcional, changeset e Apply Gate, sondas de backends dependentes de filesystem, WSL2.

Cada item exige autorização humana específica; esta ADR não autoriza nenhum deles.

## 15. Referências oficiais consultadas (acesso em 25/10/2026)

A documentação do man-pages (man7.org) é a versão corrente publicada, não vinculada a um kernel específico; versões de kernel citadas são as que as próprias páginas informam. Páginas do GitHub foram lidas na ramificação padrão, salvo indicação de tag.

- landlock(7): https://man7.org/linux/man-pages/man7/landlock.7.html
- Kernel, Landlock: https://www.kernel.org/doc/html/latest/security/landlock.html
- mount_namespaces(7): https://man7.org/linux/man-pages/man7/mount_namespaces.7.html
- user_namespaces(7): https://man7.org/linux/man-pages/man7/user_namespaces.7.html
- ptrace(2): https://man7.org/linux/man-pages/man2/ptrace.2.html
- statx(2) (`STATX_MNT_ID` 5.8, `STATX_MNT_ID_UNIQUE` 6.8, `stx_mask`): https://man7.org/linux/man-pages/man2/statx.2.html
- inotify(7): https://man7.org/linux/man-pages/man7/inotify.7.html
- memfd_create(2): https://man7.org/linux/man-pages/man2/memfd_create.2.html
- fcntl(2): https://man7.org/linux/man-pages/man2/fcntl.2.html e selos em https://man7.org/linux/man-pages/man2/F_ADD_SEALS.2const.html
- prctl(2): https://man7.org/linux/man-pages/man2/prctl.2.html; https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html; https://man7.org/linux/man-pages/man2/PR_SET_NO_NEW_PRIVS.2const.html
- openat2(2) (Linux 5.6): https://man7.org/linux/man-pages/man2/openat2.2.html
- renameat2(2) (Linux 3.15): https://man7.org/linux/man-pages/man2/renameat2.2.html
- open_tree(2): https://man7.org/linux/man-pages/man2/open_tree.2.html
- ioctl_ficlone(2): https://man7.org/linux/man-pages/man2/ioctl_ficlone.2.html
- fs-verity: https://docs.kernel.org/filesystems/fsverity.html
- bubblewrap README: https://github.com/containers/bubblewrap/blob/main/README.md
- bubblewrap v0.12.0, notas de release: https://github.com/containers/bubblewrap/releases/tag/v0.12.0
- bubblewrap v0.12.0, opções (`bwrap.xml` na tag): https://raw.githubusercontent.com/containers/bubblewrap/v0.12.0/bwrap.xml
- sandbox-runtime README (ramificação padrão): https://github.com/anthropic-experimental/sandbox-runtime

**Não verificado:** (a) a **versão 0.0.81 do SRT** não foi confirmada em nenhuma das páginas lidas (o README foi lido na ramificação padrão, não em tag correspondente; a página do pacote npm não pôde ser carregada); a fixação em 0.0.81 vem dos registros do próprio repositório; (b) as seções do README do SRT sobre limitações foram lidas de forma parcial (cerca de 100 mil dos 114 mil caracteres, mais o trecho final sobre Windows); (c) a hipótese sobre `ctime` não definível pelo usuário; (d) snapshots de filesystems específicos (Btrfs/XFS) e a disponibilidade de qualquer recurso no ext4 do proprietário; (e) comportamento de fds herdados sob SRT. As afirmações correspondentes são hipóteses.

## 16. Histórico de revisões

- **f13ad41** — versão inicial do PR-A.
- Primeira auditoria independente do Codex (read-only, HEAD `f13ad41`): **REPROVADO, 4 P1 e 6 P2**, sem P0. Esta revisão trata: C5 (separado em C5a/C5b/C5c), garantia prematura de A1 (substituída por objetivos `NOT_VERIFIED` e pelo vocabulário da seção 0), premissa de fds (seção 7.1), compare-and-swap do Apply Gate (seção 7.8), alcance de A3 (3.1), `RESOLVE_NO_XDEV` (7.2), `nlink` e criação de diretórios/arquivos (7.4, 7.5), memfd (8.4), identidade de montagem (7.2) e referências (seção 15). O parecer original é preservado aqui e na descrição do PR #29.
- Segunda auditoria Codex: **pendente**. Aprovação humana: **pendente**.
