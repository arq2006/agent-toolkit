# ADR-012 — Fronteiras de confiança para snapshot e supervisor (GH-F1.18)

**Status:** proposta, **somente documental** (PR-A da GH-F1.18; 25/10/2026; revisada após duas auditorias Codex, ver seção 16). Esta ADR registra decisões arquiteturais propostas para uma arquitetura **experimental**. Nada aqui está implementado. `STRONG=UNAVAILABLE` e `readiness=BLOCKED` permanecem invariantes; nenhuma flag de autorização muda (`agent_execution_authorized`, `file_operations_authorized`, `cloud_call_authorized`, `data_transfer_authorized` seguem `false`). **A aprovação desta ADR não desbloqueia a execução de agentes.** A terceira auditoria independente do Codex, sobre o HEAD corrigido, está **pendente**. Os componentes das seções 6, 7, 9 e 11 são propostas, não funcionalidades.

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

**Ambiente informado pelo proprietário (25/10/2026), não comprovado como capacidade de segurança:** Arch Linux; filesystem `ext4` (o `stat -f` do proprietário reporta o nome de família `ext2/ext3`); kernel `7.2.4-arch1-2`. Isto descreve o ambiente do MVP e **não** estabelece que reflink, snapshot atômico de árvore ou fs-verity estejam disponíveis: tais capacidades dependem do filesystem e das opções efetivas e devem ser verificadas por teste. Nenhuma suposição sobre o filesystem de outras máquinas é feita a partir do checkout em nuvem.

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
   → Apply Gate                         ← processo separado; único caminho concedido às alterações originadas pela célula, com aprovação humana
```

**O que cruza uma fronteira.** Uma fronteira pode transportar (a) **dados serializados** ou (b) **capacidades explicitamente autorizadas e inventariadas**. São capacidades, e não simples dados: descritores de arquivo, montagens (inclusive bind mounts), sockets e canais IPC, o diretório de trabalho herdado, o terminal controlador e, por consequência, qualquer descritor passado por `SCM_RIGHTS`. Dados de configuração como variáveis de ambiente influenciam o comportamento do processo e entram no inventário. Nada atravessa por herança implícita. Cada capacidade concedida à célula deve constar de um inventário com identidade e finalidade; o que não consta é negado. Isto é um **requisito arquitetural futuro, `NOT_VERIFIED`**.

O Apply Gate é o **único caminho concedido às alterações originadas pela célula**; ele **não** é o único caminho de escrita na origem: A2 e A3 continuam capazes de alterar a origem por caminhos externos. O supervisor não confia em: conteúdo da pasta, nomes, symlinks, `.git` e configurações internas, saída da célula, JSON produzido por qualquer agente. A identidade de uma pasta (seção 7.2) **não** equivale a autorização autenticada nem exclui escritores do mesmo UID.

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

### 7.1 Supervisor e células: requisitos de bootstrap, capacidades e ciclo de vida (futuros)

Estado atual: nenhum dos requisitos abaixo está implementado ou testado de forma geral (o launcher atual constrói o ambiente do zero apenas para os canários sintéticos). **Todas as propriedades a seguir permanecem `NOT_VERIFIED`.** Nenhum mecanismo isolado resolve o conjunto; cada item exige implementação e testes positivos e negativos próprios. A premissa de que apenas descritores acima de 2 seriam perigosos é incorreta: 0, 1 e 2 também podem referenciar capacidades sensíveis (sockets, arquivos, diretórios, terminais, pipes de outros processos).

1. **Capacidades.** FDs, mounts, sockets e canais IPC são capacidades (seção 4), não dados. Cada processo recebe somente as listadas num inventário de concessão.
2. **Ambiente.** Todo processo (supervisor e células) inicia com ambiente construído **por allowlist a partir de ambiente vazio**; nenhuma variável é herdada por omissão. O ambiente passado a `execve` é o `envp` explícito.
3. **Diretório de trabalho.** O `cwd` é definido explicitamente (por exemplo `fchdir` a um descritor validado) para um diretório **dentro da fronteira autorizada** da célula; nunca herdado.
4. **FDs 0, 1 e 2.** São substituídos por endpoints **criados ou validados pelo supervisor**, com identidade e finalidade definidas (por exemplo `/dev/null` aberto pelo supervisor, ou um pipe criado por ele para captura de saída). Nota de documentação: `dup`/`dup2` fazem o novo descritor compartilhar a *open file description* (offset e flags de status) com o original e deixam `FD_CLOEXEC` desligado, o que é necessário para 0–2 atravessarem `execve`, mas significa que duplicar um descritor sensível propaga a sua autoridade; por isso o endpoint deve ser criado, não duplicado de um descritor herdado.
5. **Terminal controlador.** É uma capacidade. Proposta: o filho chama `setsid()` para iniciar **nova sessão sem terminal controlador** (a chamada falha com `EPERM` se o chamador for líder de grupo; usar `fork` e chamar no filho), e terminais são abertos com `O_NOCTTY` para não adquirir um controlador por acidente. A mitigação de `TIOCSTI` segue a documentação do bubblewrap: sem filtro seccomp de `TIOCSTI` é preciso `--new-session`; o man do kernel registra que desde o Linux 6.2 `TIOCSTI` pode exigir `CAP_SYS_ADMIN` **somente** quando o sysctl `dev.tty.legacy_tiocsti` é falso, sem informar o padrão. Portanto não se depende do padrão do sistema.
6. **Inventário de FDs.** Feito por mecanismo apropriado, como a leitura de `/proc/self/fd` (tipo e destino de cada entrada), executada em processo monothread e com `/proc` verificado. **`close_range` não realiza inventário**: retorna apenas sucesso ou erro; a própria página do man usa `/proc/self/fd` para listar descritores.
7. **Fechamento.** `close_range` pode fechar descritores ou marcá-los `CLOEXEC` (`CLOSE_RANGE_CLOEXEC`, Linux 5.11), e `CLOSE_RANGE_UNSHARE` desassocia a tabela de descritores antes de fechar, evitando corridas com threads que a compartilham (Linux 5.9 / glibc 2.34 para a chamada). Isso **não substitui uma política de allowlist**: é a ferramenta para aplicá-la.
8. **Preservação sem herança acidental.** Procedimento conceitual: abrir tudo com `O_CLOEXEC` (essencial em programas com threads, segundo `open(2)`); no filho, após `fork`, posicionar os descritores autorizados em números definidos (por exemplo com `dup3` e `O_CLOEXEC` onde não devam sobreviver ao `exec`, ou limpando `FD_CLOEXEC` somente nos que devam), marcar o restante `CLOEXEC`/fechar com `close_range` e só então executar. Os números e flags finais são verificados por reinventário (item 9).
9. **Revalidação imediatamente antes de cada `execve`.** O filho reinventaria `/proc/self/fd` e compara com a allowlist; qualquer divergência aborta. Lembrete: descritores sem `CLOEXEC` atravessam `execve`, e bits set-user-ID/capabilities são ignorados com `no_new_privs`.
10. **IPC e `SCM_RIGHTS`.** **Proibidos por padrão.** Quando autorizados: canal `AF_UNIX` criado pelo supervisor (par de sockets), nunca socket por caminho ou abstrato acessível a terceiros (o man de `unix(7)` avisa que permissões de arquivo de socket não devem ser base de segurança, e que sockets abstratos independem de permissões de arquivo); `SO_PEERCRED` informa apenas credenciais no momento do `connect`/`socketpair` e não autentica propósito; descritores recebidos referenciam a mesma *open file description* do remetente, portanto carregam a autoridade completa; cada descritor recebido é validado (tipo, `fstat`/identidade, flags) antes do uso e os inesperados são fechados; limite de quantidade (o man informa 253 por mensagem em kernels atuais). Se `MSG_CMSG_CLOEXEC` está disponível para o recebimento não foi confirmado nas páginas consultadas (hipótese).
11. **Ciclo de vida.** Filhos e descendentes permanecem sob a fronteira correspondente e são encerrados em conjunto com o pai: o supervisor mantém a sessão e o grupo de processos da célula e os encerra no término ou no timeout (o launcher atual faz isso para os canários). Um descendente pode escapar de um grupo de processos (`setsid`, dupla bifurcação); contê-lo exige um mecanismo adicional (por exemplo namespace de PIDs, que o bubblewrap oferece com `--unshare-pid`, ou controle por cgroup), cuja suficiência **não foi verificada**.
12. **Limites do SRT e do Landlock para descritores preexistentes.** O Landlock não restringe arquivos abertos antes da restrição e mantém os direitos associados ao descritor mesmo quando repassado; portanto o inventário e o fechamento têm de ocorrer **antes** de aplicar a restrição ou lançar a célula. No README do SRT v0.0.81 o único tratamento visível de descritores herdados é o `--control-fd`, que o comando isolado recebe como `/dev/null`; **não encontrei afirmação geral sobre herança de descritores**, logo o comportamento do SRT com fds preexistentes é `NOT_VERIFIED`.
13. **Demais hardening.** `PR_SET_NO_NEW_PRIVS` (irreversível, herdado por filhos e preservado em `execve`); recusa de `euid==0`; `PR_SET_DUMPABLE=0` é hardening limitado (seção 3.1).

### 7.2 Raiz confiável e identidade

O supervisor abre a pasta ele mesmo, a partir de `/`, componente a componente com `openat2` (`RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, `RESOLVE_NO_XDEV`; `RESOLVE_BENEATH` quando houver `dirfd` ancorado). Depois disso o contrato opera **preferencialmente sobre o `root_fd` já aberto**, sem nova resolução por pathname.

**Obtenção de metadados.** `fstat(fd)` e `statx(fd, "", AT_EMPTY_PATH, mask, &stx)` são chamadas distintas: com `AT_EMPTY_PATH` e caminho vazio, `statx` opera sobre o arquivo referido pelo `fd` (o `fd` pode ser de qualquer tipo, inclusive `O_PATH`; caminho `NULL` apenas desde o Linux 6.11) e é a única via documentada que informa o identificador de montagem e uma **máscara** de campos preenchidos (`stx_mask`). A comparação de qualquer valor com uma observação anterior é apenas isso: igualdade de metadados.

**Campos exigidos (requisitos mínimos escolhidos):**
- `STATX_INO` ligado em `stx_mask` (faz parte de `STATX_BASIC_STATS`). A máscara retornada pode diferir da solicitada: o kernel pode omitir campos pedidos ou preencher campos não pedidos, e um campo só vale se o bit correspondente estiver ligado.
- Dispositivo: `stx_dev_major`/`stx_dev_minor` **não têm bit próprio** na documentação consultada (não existe `STATX_DEV`), e a página também não afirma que sejam sempre preenchidos; esta ADR não exige um bit inexistente. O contrato compara o dispositivo com o obtido por `fstat` e **recusa** se houver inconsistência; o comportamento empírico será verificado no PR-B.
- Identificador de montagem: preferir `STATX_MNT_ID_UNIQUE` (Linux 6.8; a página o descreve como não reutilizado enquanto o sistema está em execução); aceitar `STATX_MNT_ID` (Linux 5.8; a página não diz se pode ser reutilizado) somente se o bit correspondente estiver ligado. **Registrar qual variante foi obtida** (`unique`, `legacy` ou `ausente`); valores de variantes diferentes não são comparáveis entre si. Variante ausente ⇒ identidade parcial ⇒ **recusa**.
- Os campos de **uma mesma estrutura `statx` não formam um snapshot atômico**: a documentação diz que campos diferentes podem refletir momentos diferentes. Reobservar e comparar não elimina a corrida.
- Escopo por mount namespace: a documentação consultada não o trata. Registrar o namespace observado (por exemplo o link de `/proc/self/ns/mnt`) apenas como contexto; nada autoriza supor validade de um identificador fora do namespace em que foi observado.

Esses campos ajudam a **comparar** o objeto e a montagem observados agora com os observados antes. **Igualdade de metadados não é autenticidade da origem**: não autentica o proprietário, não recupera objeto histórico e não exclui escritores do mesmo UID. A reabertura é descrita como *reabrir a pasta e comparar a identidade atual com a registrada*; divergência, ou requisito mínimo não atendido, resulta em recusa.

**`RESOLVE_NO_XDEV` e pontos de montagem.** A flag recusa qualquer travessia de ponto de montagem, **inclusive bind mounts legítimos**, com `EXDEV`; a documentação alerta que o uso amplo pode gerar erros espúrios onde bind mounts são comuns (por exemplo uma pasta de projeto que contém um subdiretório montado). Decisão proposta: **manter a recusa por padrão** e tratá-la como recusa legítima. Qualquer futura permissão para atravessar montagens exige âncoras explicitamente autorizadas pelo proprietário e verificação explícita (identidade da montagem, tipo de filesystem, destino); `NO_XDEV` **não será relaxado silenciosamente**.

### 7.3 Concessão do proprietário (futura)

Ver seção 9.

### 7.4 Captura controlada

Produz `SnapshotHandle` com identificador, digest do manifesto, nível de consistência e as evidências coletadas. Níveis possíveis: `DETECTED_STABLE` (nenhuma evidência de instabilidade observada; **não** é garantia), `ATOMIC_BACKEND` (somente quando backend atômico foi sondado e declarado) e `REFUSED_UNSTABLE`. Aceita apenas diretórios e **arquivos regulares**; arquivos regulares exigem `st_nlink == 1`. **Diretórios não estão sujeitos a `nlink==1`** (em muitos filesystems o `st_nlink` de um diretório reflete subdiretórios e não indica hardlink perigoso; o valor depende do filesystem). Copia bytes; nunca usa `link`, `rename` ou reflink da origem sem decisão específica.

### 7.5 Snapshot Store

- **Criação de diretórios:** `mkdirat` sob um diretório pai confiável (aberto e validado pelo supervisor, sem symlinks nos componentes), seguido de **abertura do diretório criado com `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` e validação** (tipo, dono, modo, `dev`/`ino`) antes de qualquer uso. A criação de diretório não usa `O_EXCL` (flag de `open`, não de `mkdirat`); a exclusividade vem de `mkdirat` falhar com `EEXIST` quando o nome existe.
- **Criação de arquivos regulares:** `openat` com `O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC` (e modo restritivo), nunca reutilizando nomes existentes; depois `fstat` para conferir tipo regular e `st_nlink == 1`.
- Manifesto com digest, selo e `verify` reexecutável no lançamento e ao final da célula. `chmod` e um digest isolado **não** são prova de imutabilidade contra A3: servem como convenção contra A1/A2 e como evidência de adulteração, com resíduo declarado.

### 7.6 Célula isolada

Extensão futura de `srt_launcher`: vê somente a cópia do store, por montagem somente leitura, mais área de trabalho separada; objetivo: sem rede e sem acesso à origem. **Montagens são capacidades**: um bind mount concede acesso a objetos do filesystem. Um bind mount somente leitura restringe escritas *por aquele caminho de montagem*, mas **não congela o backing store**: um escritor externo (A2 ou A3) pode continuar alterando o conteúdo por outro caminho que lhe seja acessível, e o que a célula lê pode mudar durante a execução. Montagem somente leitura **não equivale a snapshot imutável**; a independência vem da cópia feita pela captura (seção 7.4) e continua sujeita à seção 8. O inventário da célula deve cobrir montagens, descritores, IPC, ambiente, `cwd`, terminal controlador e demais capacidades (seção 7.1). A célula e sua proteção permanecem `NOT_VERIFIED`: dependem de inventário de capacidades (versões SRT 0.0.81 e bubblewrap 0.12.0, seccomp, user namespaces) e de testes positivos e negativos em cada ambiente.

### 7.7 ChangeSet

Esquema fechado `{op, path, base_digest, new_digest}` + blobs (dado serializado, não capacidade); proibidos por padrão symlink, hardlink, dispositivos, mudança de modo além do bit executável e caminhos protegidos (`.git/**`, `.claude/**`, `.mcp.json`, rc de shell, definições de CI).

### 7.8 Apply Gate

Processo separado, sem agente; é o único caminho concedido às alterações originadas pela célula (A2 e A3 continuam podendo alterar a origem por caminhos externos). Exibe o diff; exige aprovação humana vinculada a `hash(changeset, manifesto-base, identidade atual comparada)` com expiração e sem reutilização.

**Limites que valem para todas as operações:**
- Comparar `base_digest` e depois realizar uma mutação **não é compare-and-swap atômico**: são etapas separadas, com janela entre elas.
- Divergência observada **antes** da mutação ⇒ recusa ou conflito.
- Divergência que surja **depois** da verificação pode não ser percebida antes da operação.
- Atualizações, remoções e alterações de permissões podem atingir conteúdo ou objetos **diferentes** dos aprovados.
- Verificação posterior é **detecção após a mutação**: não é garantia de reversão, de transação nem de ausência de perda.
- `renameat2` documenta apenas operações de nomes. `RENAME_NOREPLACE` falha se o destino já existe e é útil para **criação** de destino inexistente; não resolve CAS de conteúdo de arquivo existente. `RENAME_EXCHANGE` troca nomes atomicamente, mas **também não resolve, sozinho, atualização condicional de conteúdo**: nenhuma das flags compara conteúdo.
- Não se projeta aqui nenhum mecanismo transacional; isso exigiria exclusão de escritores ou fronteira adicional, ainda inexistentes.

| Operação | Mecanismo conceitual | O que se pode dizer | Estado |
|---|---|---|---|
| **Criar arquivo novo** | arquivo temporário completo no mesmo diretório + `renameat2(RENAME_NOREPLACE)` | recusa se o nome de destino já existir no instante da chamada (conflito) | `NOT_VERIFIED` até teste |
| **Atualizar arquivo existente** | comparar identidade/`base_digest`, preparar substituto, trocar | janela entre comparação e troca; um escritor concorrente pode alterar o arquivo no intervalo. Se `RENAME_EXCHANGE` for usado, o objeto deslocado pode ser examinado depois e uma divergência é **detectada após a mutação**, sem garantia de reversão | **`NOT_VERIFIED`** |
| **Remover** | verificar identidade, `unlinkat` | `unlinkat` não verifica conteúdo; pode remover objeto diferente do revisado | **`NOT_VERIFIED`** |
| **Alterar permissões** | abrir o arquivo (sem `O_PATH`), validar identidade no descritor e usar `fchmod(fd, modo)` | `fchmod` atua diretamente no arquivo referido pelo descritor, o que reduz o risco de troca de nome entre verificação e uso, mas **não resolve** conflito com o conteúdo aprovado. Um descritor `O_PATH` não serve a `fchmod` (`EBADF`, segundo `open(2)`) | **`NOT_VERIFIED`** |

**`fchmod` × `fchmodat`.** `fchmod(fd, modo)` atua no arquivo referido pelo descritor. `fchmodat(dirfd, path, ..., flags)` normalmente envolve resolução do caminho relativo a `dirfd`. `fchmodat` com caminho vazio e `AT_EMPTY_PATH` é suportado pelo kernel somente desde o Linux 6.6 segundo o man e depende de suporte de libc; `AT_SYMLINK_NOFOLLOW` tem histórico próprio (glibc 2.32, Linux 6.5). Qualquer uso de `fchmodat` exige verificação de suporte no ambiente antes; o desenho conceitual prefere `fchmod` sobre descritor aberto e validado.

O Apply Gate permanece **`NOT_VERIFIED` para qualquer operação que exija exclusão de escritores ou semântica transacional**. O Apply Gate também não executa `git` na origem do usuário (configuração, hooks e filtros do repositório podem executar código).

## 8. Limitações de detecção e atomicidade

### 8.1 Evidências de detecção, não garantias

`ctime`, `mtime`, inotify e releituras são **evidências de detecção** sujeitas a:
- resolução e granularidade dos timestamps (alterações dentro da mesma unidade de tempo podem ser indistinguíveis);
- concorrência entre a observação e a leitura;
- eventos não observados: segundo inotify(7), acessos e modificações via `mmap(2)`, `msync(2)` e `munmap(2)` **não são reportados**; mudanças remotas em sistemas de arquivos de rede não são capturadas; pseudo-filesystems não podem ser monitorados;
- overflow da fila (`IN_Q_OVERFLOW`, limitado por `max_queued_events`), limites `max_user_watches`/`max_user_instances`, observação **não recursiva** (subdiretório novo pode já conter arquivos antes de o watch ser instalado), correspondência racy de `IN_MOVED_FROM`/`IN_MOVED_TO`, coalescência de eventos idênticos e impossibilidade de identificar o autor do evento;
- limitações do filesystem e das opções de montagem.

Não se afirma que `ctime` elimina ou sempre detecta ABA. A hipótese de que `ctime` não é definível pelo usuário comum e por isso torna detectável um subconjunto de A→B→A feito por `write()`/`truncate()` **não está confirmada pela documentação consultada** (`inode(7)` diz que `ctime` muda com escrita ou alteração de metadados e cita `utime` só para atime/mtime, sem afirmar que o usuário não possa defini-lo) e deve ser **medida** no ambiente (PR-C), reportada como resultado experimental com resíduos. Um hash descreve os bytes lidos, não a estabilidade entre leituras.

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
- **P3** objetivo: célula sem acesso à origem nem a store gravável, com inventário completo de capacidades (propriedade testável com controles positivo e negativo; montagem somente leitura não equivale a snapshot imutável);
- **P4** changeset verificado com aprovação humana vinculada (sem promessa de atomicidade da aplicação, seção 7.8);
- **P5** (opcional) captura atômica, somente com backend sondado;
- **P6** (opcional) conteúdo do store protegido por mecanismo do filesystem.

## 12. Critérios verificáveis de aceite e recusa

**Aceite (por PR futuro):** cada propriedade tem teste negativo com controle positivo no mesmo run; ausência de resultado, exceção, timeout ou tipo malformado = `NOT_VERIFIED`; `SKIP` por kernel não conta como prova; execução no Arch reportada com HEAD exato; auditoria Codex read-only antes do merge; aprovação humana específica por PR.

**Resultados de corrida.** Um número finito de execuções sem falhas **não** constitui prova matemática de ausência de ABA. Todo relatório de corrida deve declarar: quantidade de execuções, condições (kernel, filesystem, opções de montagem, carga, estratégia do escritor), resultados observados (inclusive aceitações inconsistentes e recusas), limitações e resíduos desconhecidos. Resultados experimentais são distinguidos de garantias.

**Recusa:** kernel ou syscall necessária ausente; inventário de capacidades da célula incompleto ou com item não autorizado (montagem, descritor, canal IPC, variável de ambiente, `cwd`, terminal controlador); filesystem não suportado ou não verificado; qualquer fd não previsto na allowlist (inclusive 0–2); travessia de montagem não autorizada (`EXDEV`); campo de identidade ausente na máscara retornada; instabilidade observada além do limite de tentativas; inotify indisponível, com overflow ou sem cobertura de um diretório novo; arquivo regular com `nlink>1`; arquivo especial; store com permissões diferentes das esperadas; digest divergente no lançamento; qualquer relatório que afirme `aba_protection_proven`, `STRONG`, isolamento de escritores não cooperativos, atomicidade da aplicação ou ausência de sobrescrita concorrente sem prova correspondente.

**Linguagem proibida até haver prova:** "elimina ABA", "isolado de escritores", "STRONG", "proveniência verificada contra adversário", "garantia por construção", "dados, nunca capacidades", "único caminho de escrita na origem", "sem sobrescrita concorrente", "CAS atômico" (para a aplicação), "snapshot imutável" (para montagem somente leitura). Permitida: "objetivo", "detectado", "recusado se instável", "resíduo medido", "A3 fora da garantia", "NOT_VERIFIED".

## 13. Riscos conhecidos e requisitos não resolvidos

- A3 sem proteção, com alcance sobre toda a cadeia (seção 3.1); proteção por C5a/C5c condicional e não verificada, C5b insuficiente isoladamente.
- A1 é objetivo `NOT_VERIFIED`; SRT 0.0.81 (beta) e bubblewrap 0.12.0 não foram revalidados para as novas montagens; padrões de deny ignorados no Linux falham abertos (documentação do SRT); bubblewrap é ferramenta de construção cujo nível de proteção depende dos argumentos e do que é montado (README do bubblewrap).
- Descritores herdados: protocolo da seção 7.1 não implementado; comportamento do SRT com fds preexistentes não verificado.
- Apply Gate sem atomicidade para atualização, remoção e permissões (seção 7.8); divergências posteriores à verificação podem passar despercebidas.
- Capacidades (descritores, montagens, IPC, ambiente, `cwd`, terminal controlador) e ciclo de vida de descendentes: requisitos da seção 7.1 não implementados; contenção de descendentes que escapam do grupo de processos não verificada.
- Montagem somente leitura não congela o backing store (seção 7.6).
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

## 15. Referências oficiais consultadas (acesso em 25 e 26/10/2026)

**Convenção.** As páginas do man-pages (man7.org) são a versão corrente publicada e **não** estão vinculadas a um kernel específico; versões de kernel citadas são as que as próprias páginas informam. Para as ferramentas com versão fixada, as referências abaixo são **tags**, não a ramificação padrão. Itens marcados *(lida)* tiveram o conteúdo conferido antes de qualquer afirmação técnica; o que não foi lido consta na lista de não verificados.

**Kernel e man-pages**
- statx(2) *(lida)*: https://man7.org/linux/man-pages/man2/statx.2.html
- inode(7) *(lida)*: https://man7.org/linux/man-pages/man7/inode.7.html
- inotify(7) *(lida)*: https://man7.org/linux/man-pages/man7/inotify.7.html
- execve(2) *(lida)*: https://man7.org/linux/man-pages/man2/execve.2.html
- close_range(2) *(lida)*: https://man7.org/linux/man-pages/man2/close_range.2.html
- open(2) *(lida)*: https://man7.org/linux/man-pages/man2/open.2.html
- dup(2) *(lida)*: https://man7.org/linux/man-pages/man2/dup.2.html
- chmod(2), fchmod, fchmodat *(lida)*: https://man7.org/linux/man-pages/man2/chmod.2.html
- openat2(2) *(lida)*: https://man7.org/linux/man-pages/man2/openat2.2.html
- renameat2(2) *(lida)*: https://man7.org/linux/man-pages/man2/renameat2.2.html
- setsid(2) *(lida)*: https://man7.org/linux/man-pages/man2/setsid.2.html
- TIOCSTI *(lida)*: https://man7.org/linux/man-pages/man2/TIOCSTI.2const.html
- unix(7), `SCM_RIGHTS` *(lida)*: https://man7.org/linux/man-pages/man7/unix.7.html
- prctl(2) *(lida)*: https://man7.org/linux/man-pages/man2/prctl.2.html; `PR_SET_DUMPABLE` https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html; `PR_SET_NO_NEW_PRIVS` https://man7.org/linux/man-pages/man2/PR_SET_NO_NEW_PRIVS.2const.html
- memfd_create(2) *(lida)*: https://man7.org/linux/man-pages/man2/memfd_create.2.html
- fcntl(2) e selos *(lida)*: https://man7.org/linux/man-pages/man2/fcntl.2.html; https://man7.org/linux/man-pages/man2/F_ADD_SEALS.2const.html
- ptrace(2) *(lida)*: https://man7.org/linux/man-pages/man2/ptrace.2.html
- user_namespaces(7) *(lida)*: https://man7.org/linux/man-pages/man7/user_namespaces.7.html
- mount_namespaces(7) *(lida)*: https://man7.org/linux/man-pages/man7/mount_namespaces.7.html
- open_tree(2) *(lida)*: https://man7.org/linux/man-pages/man2/open_tree.2.html
- ioctl_ficlone(2) *(lida)*: https://man7.org/linux/man-pages/man2/ioctl_ficlone.2.html
- landlock(7) *(lida)*: https://man7.org/linux/man-pages/man7/landlock.7.html
- Kernel, Landlock (documentação corrente) *(lida)*: https://www.kernel.org/doc/html/latest/security/landlock.html
- Kernel, fs-verity (documentação corrente) *(lida)*: https://docs.kernel.org/filesystems/fsverity.html

**Versões fixadas**
- Bubblewrap v0.12.0, notas de release *(lida)*: https://github.com/containers/bubblewrap/releases/tag/v0.12.0
- Bubblewrap v0.12.0, README da tag *(lida)*: https://github.com/containers/bubblewrap/blob/v0.12.0/README.md
- Bubblewrap v0.12.0, opções (`bwrap.xml` na tag) *(lida)*: https://raw.githubusercontent.com/containers/bubblewrap/v0.12.0/bwrap.xml
- Sandbox Runtime v0.0.81, release *(lida)*: https://github.com/anthropics/sandbox-runtime/releases/tag/v0.0.81
- Sandbox Runtime v0.0.81, README da tag *(lida; cerca de 100 mil dos 113 mil caracteres mais o trecho final sobre Windows)*: https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/README.md
- Já citadas por documentos do repositório: symlink(7).

**Fatos confirmados nas fontes lidas (exemplos usados nesta ADR):** existência da tag e do README do SRT v0.0.81 (release de 20/10, com mudanças descritas apenas para Windows; macOS e Linux inalterados); bubblewrap v0.12.0 documenta `--ro-bind-data`, `--bind-data`, `--file`, `--new-session`, `--disable-userns`, `--die-with-parent`, `--not-a-security-boundary` e não documenta `--bind-fd`/`--ro-bind-fd`; o README do bubblewrap v0.12.0 exige `--new-session` na ausência de filtro seccomp de `TIOCSTI`; `close_range` não enumera descritores; `statx` não oferece bit para `stx_dev_major/minor`; `RENAME_NOREPLACE`/`RENAME_EXCHANGE` não comparam conteúdo.

**Hipóteses e itens não verificados:**
- A hipótese de que o usuário comum não consegue definir `ctime` (a página `inode(7)` diz apenas que `ctime` muda com escrita ou alteração de metadados e cita `utime` somente para atime/mtime).
- Comportamento do SRT v0.0.81 e do bubblewrap v0.12.0 com descritores herdados (nenhuma das duas fontes lidas o descreve de forma geral) e se `MSG_CMSG_CLOEXEC` está disponível no recebimento (a página `unix(7)` consultada não o cobre).
- Escopo por mount namespace dos identificadores de montagem.
- Um trecho final do README do SRT v0.0.81 não foi lido; não foi encontrada seção de limitações específica de Linux.
- Snapshots de filesystems específicos (Btrfs/XFS) e a disponibilidade de reflink, snapshot atômico ou fs-verity no ext4 do proprietário.
- Suficiência de namespace de PIDs ou cgroups para conter descendentes.

## 16. Histórico de revisões

- **f13ad41** — versão inicial do PR-A.
- Primeira auditoria independente do Codex (read-only, HEAD `f13ad41`): **REPROVADO, 4 P1 e 6 P2**, sem P0.
- **235d182** — primeira rodada de correções (C5 separado em C5a/C5b/C5c; objetivos `NOT_VERIFIED`; protocolo inicial de fds; Apply Gate sem CAS atômico; alcance de A3; `NO_XDEV`; `nlink` e criação; memfd; identidade de montagem; referências).
- Segunda auditoria Codex (HEAD `235d182`): **REPROVADO, 2 P1, 3 P2 e 2 P3** remanescentes.
- Segunda rodada de correções (esta revisão): P1-01 bootstrap, capacidades e ciclo de vida (seções 4 e 7.1); P1-02 Apply Gate sem promessa de ausência de sobrescrita (seções 4, 7.7, 7.8, 12); P2-01 bind mounts como capacidades (4, 7.6); P2-02 `statx` e identidade de `root_fd` (7.2); P2-03 `fchmod` × `fchmodat` (7.8); P3-01 referências rastreáveis e versionadas (15); P3-02 ambiente descrito sem caminhos locais pessoais (1). O parecer das duas auditorias é preservado aqui e na descrição do PR #29.
- Terceira auditoria Codex: **pendente**. Aprovação humana: **pendente**.
