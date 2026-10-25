# ADR-012 — Fronteiras de confiança para snapshot e supervisor (GH-F1.18)

**Status:** proposta, **somente documental** (PR-A da GH-F1.18; 25/10/2026). Esta ADR registra decisões arquiteturais propostas para uma arquitetura **experimental**. Nada aqui está implementado. `STRONG=UNAVAILABLE` e `readiness=BLOCKED` permanecem invariantes; nenhuma flag de autorização muda (`agent_execution_authorized`, `file_operations_authorized`, `cloud_call_authorized`, `data_transfer_authorized` seguem `false`). A auditoria independente do Codex está **pendente**. Os componentes das seções 6 a 9 e 11 são propostas, não funcionalidades.

## 1. Contexto e motivação

A GH-F1.13 a F1.17 produziram, em fixtures sintéticas, evidências e limites que esta ADR consolida:

| Fase | Resultado registrado | Limite |
|---|---|---|
| GH-F1.13 | `NATIVE_HARDLINK_LEAK_REPRODUCED`: Read/Edit nativos e `open()` arbitrário ignoram `pathguard`/`openat2` | guardas são voluntários, em processo |
| GH-F1.14 | Snapshot sintético de um arquivo, por cópia de bytes (inode novo, `nlink==1`), lido sob SRT | um arquivo fictício; sem proveniência da raiz |
| GH-F1.15 | Segunda leitura detecta mutação in-place de mesmo tamanho nos 5 interleavings cooperativos | não prova ausência de ABA |
| GH-F1.16 | `ABA_UNDETECTED` reproduzido; `root_fd` antigo continua lendo árvore substituída | detecção comparava `(dev, ino, size)` e bytes |
| GH-F1.17 | Freeze cooperativo por `flock` funciona com escritor cooperativo; `ADVISORY_BYPASS_REPRODUCED` com escritor não cooperativo | `flock` é advisory |

Causa comum: o toolkit tenta obter, por verificações dentro de um processo que **compartilha UID** com os demais escritores, propriedades que só vêm de uma fronteira construída pelo kernel em volta dos agentes ou de uma primitiva de captura atômica. Mais leituras ou hashes reduzem janelas, mas não as fecham.

**Ambiente informado pelo proprietário (25/10/2026), não comprovado como capacidade de segurança:** `findmnt -T /home/arthur/Projetos -no FSTYPE` → `ext4`; `stat -f -c '%T'` → `ext2/ext3` (nome que o `stat` usa para a família ext); `uname -r` → `7.2.4-arch1-2`. Isto descreve o ambiente do MVP e **não** estabelece que reflink, snapshot atômico de árvore ou fs-verity estejam disponíveis: tais capacidades dependem do sistema de arquivos e das opções efetivas e devem ser verificadas por teste. Nenhuma suposição sobre o sistema de arquivos de outras máquinas é feita a partir do checkout em nuvem.

## 2. Objetivo de segurança do Toolkit

Estabelecer, de forma verificável e reutilizável entre projetos, uma fronteira entre: (1) a pasta explicitamente autorizada pelo proprietário; (2) um supervisor confiável; (3) a preparação de snapshots independentes; (4) a célula de execução isolada dos agentes; (5) a futura aplicação de alterações, mediante aprovação humana. A fronteira não pode depender apenas de instruções em prompts, locks voluntários ou verificações de caminho.

O objetivo é proteger **(i)** dados fora da pasta autorizada contra processos sob controle do supervisor, **(ii)** a coerência do que o agente lê e **(iii)** a integridade do que é aplicado de volta ao projeto. Não é objetivo proteger o projeto contra outro processo malicioso do mesmo usuário, que já poderia escrevê-lo diretamente.

## 3. Modelo de ameaças

| Classe | Descrição | Tratamento proposto |
|---|---|---|
| **A1** | Agentes e subprocessos sob controle do supervisor (incluindo ferramentas e hooks que o supervisor lançar) | Principal fronteira a isolar: garantia **por construção**, sujeita a testes negativos |
| **A2** | Escritores honestos concorrentes (editor, git, bundler, watchers, gerenciadores de pacote que criam hardlinks) | Observação, detecção e **recusa**; causam inconsistência, não malícia |
| **A3** | Escritor malicioso do mesmo UID, fora da célula | **Fora da garantia inicial.** Apenas detecção best-effort e atestação humana, sem proteção |
| **A4** | root, kernel comprometido, hardware não confiável | Fora do escopo |

Fundamentos documentais da exclusão de A3 (consultados em 25/10/2026):
- Processos do mesmo UID geralmente passam nas verificações de ptrace; o Yama limita *attach*, não impede todas as leituras via `/proc` (ptrace(2)).
- O UID que cria um user namespace tem todas as capacidades nele; processos do namespace pai com esse UID não são excluídos dele, e criar user namespace pode enfraquecer o Yama (user_namespaces(7), ptrace(2)). Logo bubblewrap, SRT e mount namespaces restringem quem está **dentro**; não protegem o conteúdo contra o mesmo usuário **fora**.
- Landlock restringe o próprio processo e seus descendentes, não outros processos (landlock(7)).
- fs-verity impede escrita e truncamento de arquivos regulares verity, mas metadados continuam alteráveis, diretórios não são cobertos e a autenticidade do digest exige esquema próprio (documentação do kernel).

Proteção real contra A3 exigiria outro UID, MAC administrado ou VM, o que contraria as restrições do projeto (sem contas adicionais, sem Docker obrigatório, sem sudo). Isso é registrado como **bloqueio**, não como algo contornado por fallback.

## 4. Fronteiras de confiança

```text
Proprietário (confirmação interativa)   ← confiança humana
   → Supervisor                         ← confia no kernel, no Python do sistema, no código revisado do toolkit e no humano
   → Captura controlada                 ← lê a origem como dado não confiável; não executa nada dela
   → Snapshot Store                     ← dado selado e reverificável; não é imutável contra A3
   → Célula isolada (SRT/bwrap, ...)    ← A1; sem rede; sem acesso à origem
   → ChangeSet                          ← dado fechado; nunca patch executável
   → Apply Gate                         ← processo separado; único caminho de escrita na origem, com aprovação humana
```

Cada seta transporta **dados**, nunca capacidades (sem fds, caminhos vivos ou comandos). O supervisor não confia em: conteúdo da pasta, nomes, symlinks, `.git` e configurações internas, saída da célula, JSON produzido por qualquer agente. A identidade de uma pasta (seção 7) **não** equivale a autorização autenticada nem exclui escritores do mesmo UID.

## 5. Arquiteturas candidatas e comparação

| ID | Arquitetura | A1 | A2 | A3 | Privilégio | Principais limitações |
|---|---|---|---|---|---|---|
| C0 | Status quo (pathguard, openat2, flock cooperativo) | não | parcial | não | não | guarda voluntário; ABA; `flock` advisory |
| **C1** | Supervisor + captura com detecção + store privado + célula SRT somente leitura | por construção, a testar | detecta, com resíduo | não | não | janela de resolução de timestamp, eventos não observados, sem atomicidade |
| C2 | C1 + backend de cópia atômica do filesystem | idem | atômico apenas onde o FS comprovadamente suporta | não | a verificar | `FICLONE` é por arquivo; snapshot de árvore depende do FS; indisponibilidade presumida em ext4 até verificação |
| C3 | C1 + fs-verity no store | idem | detecta | parcial (arquivos do store) | a verificar | só arquivos regulares; exige FS com recurso habilitado; metadados mutáveis |
| C4 | C1 + Landlock dentro da célula | segunda camada | detecta | não | não | autorrestritivo; fds já abertos não são restringidos; cobertura parcial de operações |
| C5 | Outro UID, VM ou container | sim | sim | sim | sim | viola restrições atuais do projeto |
| C6 | memfd selado como armazenamento | sim | sim | conteúdo em memória | não | não forma árvore para ferramentas nativas; integração com bwrap a verificar |
| C7 | FUSE supervisionado | sim | n/a | não | helper setuid | dependência pesada |

C2, C3, C4 e C6 são **alternativas opcionais**, cada uma com propriedades e limitações próprias, e só podem ser adotadas após sonda de capacidade efetiva no ambiente e nova decisão.

## 6. Arquitetura selecionada e justificativa

**C1** como base, com C2 a C4 e C6 como camadas opcionais condicionais. Justificativa: não exige privilégio, conta adicional ou Docker; torna A1 uma propriedade testável por construção; reaproveita `pathguard`, `linux_openat2_guard`, `srt_launcher` e os pilotos existentes; é explícita sobre A3; e desloca a integridade final para o Apply Gate com aprovação humana vinculada a digest.

Esta arquitetura **não elimina ABA** e **não habilita STRONG**. Ela propõe detectar a classe comum de instabilidade, recusar quando houver indícios, medir e declarar o resíduo.

## 7. Contratos conceituais dos componentes (propostas)

1. **Supervisor (boot):** higiene do processo antes de qualquer captura: recusar descritores herdados além de 0–2, não aceitar fds nem números de fd por argumento, ambiente ou arquivo, aplicar `PR_SET_NO_NEW_PRIVS`, recusar `euid==0`. `PR_SET_DUMPABLE=0` é hipótese de endurecimento contra A2 e filhos, sem efeito presumido contra A3. Hoje nenhum desses passos existe no código.
2. **Raiz confiável:** o supervisor abre a pasta ele mesmo, a partir de `/`, componente a componente com `openat2` (`RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, `RESOLVE_NO_XDEV`). Registra `dev`, `ino` e `mnt_id` **somente quando o `statx` efetivamente informar esses campos** (verificar a máscara retornada; `mnt_id` e sua variante única dependem da versão do kernel). Campo ausente ⇒ identidade parcial declarada como tal, nunca preenchida por suposição. Esses campos ajudam a identificar objeto e montagem; **não** autenticam o proprietário e **não** excluem escritores do mesmo UID.
3. **Concessão do proprietário (futura):** ver seção 9.
4. **Captura controlada:** produz `SnapshotHandle` com identificador, digest do manifesto, nível de consistência e as evidências coletadas. Níveis possíveis: `DETECTED_STABLE` (nenhuma evidência de instabilidade observada; **não** é garantia), `ATOMIC_BACKEND` (somente quando backend atômico foi sondado e declarado) e `REFUSED_UNSTABLE`. Aceita apenas diretórios e arquivos regulares com `nlink==1`; copia bytes; nunca usa `link`, `rename` ou reflink da origem sem decisão específica.
5. **Snapshot Store:** diretório privado criado pelo supervisor (`O_EXCL`, `O_NOFOLLOW`), manifesto com digest, selo e `verify` reexecutável no lançamento e ao final da célula. `chmod` e um digest isolado **não** são prova de imutabilidade contra A3: servem como convenção de proteção contra A1/A2 e como evidência de adulteração, com resíduo declarado.
6. **Célula isolada:** extensão futura de `srt_launcher`: vê somente a cópia do store, por montagem somente leitura, mais área de trabalho separada; sem rede; sem acesso à origem.
7. **ChangeSet:** esquema fechado `{op, path, base_digest, new_digest}` + blobs; proibidos symlink, hardlink, dispositivos, mudança de modo além do bit executável e caminhos protegidos (`.git/**`, `.claude/**`, `.mcp.json`, rc de shell, definições de CI) por padrão.
8. **Apply Gate:** processo separado, sem agente: reabre a origem pela identidade registrada, compara com `base_digest` (detecção de divergência ⇒ conflito, nunca sobrescrita), exibe o diff, exige aprovação humana vinculada a `hash(changeset, manifesto-base, identidade da raiz)` com expiração e sem reutilização, e escreve com `openat2` restrito à raiz e substituição sem sobrescrita. Não executa `git` na origem do usuário (configuração, hooks e filtros do repositório podem executar código).

## 8. Limitações de detecção e atomicidade

**Evidências de detecção, não garantias.** `ctime`, `mtime`, inotify e releituras são evidências sujeitas a:
- resolução e granularidade de timestamps (alterações dentro da mesma unidade de tempo podem ser indistinguíveis);
- concorrência entre a observação e a leitura;
- eventos não observados (por exemplo escritas via `mmap`, ou sistemas de arquivos sem entrega fiel de eventos);
- overflow da fila do inotify, limite de watches, diretórios criados após a instalação do watch;
- limitações do filesystem e das opções de montagem.

Não se afirma que `ctime` elimina ou sempre detecta ABA. A hipótese de que `ctime` não é definível pelo usuário comum e, por isso, torna detectável um subconjunto de A→B→A feito por `write()`/`truncate()` precisa ser **medida** no ambiente (PR-C) e reportada como resultado experimental com seus resíduos, não como propriedade. Um hash descreve os bytes lidos, não a estabilidade entre leituras.

**Atomicidade.** `FICLONE` é atômico em relação a escritas concorrentes **por arquivo** e exige o mesmo filesystem e suporte a reflink; não constitui snapshot atômico da árvore inteira. Snapshot atômico de árvore depende de recurso específico do filesystem, cuja disponibilidade e permissões **não** são presumidas (o ext4 informado não garante nenhum dos dois). Nenhum recurso dependente de filesystem é recomendado sem verificação de compatibilidade e permissões no ambiente.

**fs-verity e memfd selado** são opções com propriedades próprias: fs-verity protege conteúdo de arquivos regulares verity (não diretórios; metadados continuam mutáveis; exige recurso habilitado no FS; cópia perde o estado) e memfd selado protege conteúdo em memória (sem árvore de diretórios para ferramentas nativas). Nenhuma das duas é requisito nem foi verificada neste ambiente.

## 9. Política futura de concessão pelo proprietário

Proposta, a decidir antes do componente correspondente: concessão por confirmação interativa em terminal aberto pelo próprio supervisor, exibindo identidade da pasta, caminho resolvido, resumo do inventário e nonce, com validade limitada e vínculo à identidade e ao digest. Sem terminal interativo, recusar. O arquivo TOML de configuração expressa **intenção**, não concessão. Esta confirmação é procedural: **não é prova criptográfica nem protege contra A3**, pois o mesmo UID pode alterar a configuração. Mecanismos externos (polkit, FIDO2) dependem de decisão humana e de revisão de dependências.

## 10. Política futura de exclusões, limites e privacidade

Proposta: excluir por padrão `.git`, arquivos de segredo conhecidos (`.env*`, chaves, tokens), diretórios de dependências e artefatos de build; limites explícitos de tamanho, quantidade de arquivos, profundidade e comprimento de nomes; recusa de nomes problemáticos (NUL, quebras de linha, colisões Unicode ou de caixa); recusa de arquivos esparsos acima do limite; manifesto contendo apenas metadados e digests, sem conteúdo; nenhum dado copiado para provedores externos sem autorização explícita; logs sem conteúdo de arquivos. Qualquer exceção exige confirmação do proprietário.

## 11. Escada de propriedades experimentais

Nomes só podem ser usados com estes significados e nunca equivalem a `STRONG`:

- **P0** raiz identificada pelo supervisor (campos de identidade efetivamente disponíveis);
- **P1** captura recusada quando há evidência de instabilidade (detecção sujeita à seção 8);
- **P2** snapshot independente, `nlink==1`, selado e reverificável;
- **P3** célula sem acesso à origem nem a store gravável (por construção, com testes negativos);
- **P4** changeset verificado com aprovação humana vinculada;
- **P5** (opcional) captura atômica, somente com backend sondado;
- **P6** (opcional) conteúdo do store protegido por mecanismo do filesystem.

## 12. Critérios verificáveis de aceite e recusa

**Aceite (por PR futuro):** cada propriedade tem teste negativo com controle positivo no mesmo run; ausência de resultado, exceção, timeout ou tipo malformado = `NOT_VERIFIED`; `SKIP` por kernel não conta como prova; execução no Arch reportada com HEAD exato; auditoria Codex read-only antes do merge; aprovação humana específica por PR.

**Resultados de corrida.** Um número finito de execuções sem falhas **não** constitui prova matemática de ausência de ABA. Todo relatório de corrida deve declarar: quantidade de execuções, condições (kernel, filesystem, opções de montagem, carga, estratégia do escritor), resultados observados (inclusive aceitações inconsistentes e recusas), limitações e resíduos desconhecidos. Resultados experimentais são distinguidos de garantias.

**Recusa:** kernel ou syscall necessária ausente; filesystem não suportado ou não verificado; qualquer fd extra no boot; instabilidade observada além do limite de tentativas; inotify indisponível ou com overflow; `nlink>1`; arquivo especial; store com permissões diferentes das esperadas; digest divergente no lançamento; qualquer relatório que afirme `aba_protection_proven`, `STRONG` ou isolamento de escritores não cooperativos sem prova correspondente.

**Linguagem proibida até haver prova:** "elimina ABA", "isolado de escritores", "STRONG", "proveniência verificada contra adversário". Permitida: "detectado", "recusado se instável", "resíduo medido", "A3 fora da garantia".

## 13. Riscos conhecidos e requisitos não resolvidos

- A3 sem proteção; store e concessão não autenticáveis contra o mesmo UID.
- Resíduo de ABA dentro da resolução de timestamps e para escritas não observáveis; não quantificado ainda.
- Capacidades do ext4 do ambiente (reflink, fs-verity, snapshots) **não verificadas**; WSL2, DrvFs, NFS, FUSE e overlay não avaliados.
- Comportamento de bwrap 0.12.0 para montagem por descritor ou por dados (`--ro-bind-data` etc.) não verificado; Landlock não exercitado.
- Interação do SRT 0.0.81 (beta) com as novas montagens não revalidada; padrões de deny ignorados no Linux falham abertos (documentação do SRT).
- Proveniência de `root_fd`, bind mounts reais e worktrees reais seguem `NOT_TESTED`.
- Auditoria independente do Codex pendente.
- Política de exclusões e fonte ativa dependem de decisão humana.

## 14. Relação entre PR-A, PR-B, PR-C, PR-D e GH-F1.19+

- **PR-A (esta ADR):** documentação; nenhum código, teste, flag ou política alterada.
- **PR-B (proposto, não iniciado):** higiene do supervisor e abertura confiável da raiz, com testes em fixtures.
- **PR-C (proposto):** harness de medição das evidências de detecção, sem novo guard e sem reivindicar garantia.
- **PR-D (proposto):** captura e store, com recusa, somente em fixtures.
- **GH-F1.19+ (proposto):** concessão interativa, célula com montagem somente leitura e Landlock opcional, changeset e Apply Gate, sondas de backends dependentes de filesystem, WSL2.

Cada item exige autorização humana específica; esta ADR não autoriza nenhum deles.

## 15. Referências oficiais consultadas (acesso em 25/10/2026)

- landlock(7): https://man7.org/linux/man-pages/man7/landlock.7.html
- Kernel, Landlock: https://www.kernel.org/doc/html/latest/security/landlock.html
- mount_namespaces(7): https://man7.org/linux/man-pages/man7/mount_namespaces.7.html
- user_namespaces(7): https://man7.org/linux/man-pages/man7/user_namespaces.7.html
- ptrace(2): https://man7.org/linux/man-pages/man2/ptrace.2.html
- open_tree(2): https://man7.org/linux/man-pages/man2/open_tree.2.html
- ioctl_ficlone(2): https://man7.org/linux/man-pages/man2/ioctl_ficlone.2.html
- fs-verity: https://docs.kernel.org/filesystems/fsverity.html
- bubblewrap README: https://github.com/containers/bubblewrap/blob/main/README.md
- sandbox-runtime README (leitura parcial, cerca de 100 mil dos 114 mil caracteres; a parte final não foi lida): https://github.com/anthropic-experimental/sandbox-runtime
- Já citadas por documentos do repositório: openat2(2), symlink(7).

**Não consultadas nesta rodada** (afirmações correspondentes são hipóteses a verificar): inotify(7), statx(2), memfd_create(2) e selos de `fcntl(2)`, snapshots de filesystems específicos, prctl(2), opções de montagem por dados/descritor do bwrap.
