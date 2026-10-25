# GH-F1.9 — openat2 experimental e canário SRT de caminhos indiretos

**Estado: Draft/protótipo. Sem agentes, sem aprovação STRONG e sem integração às ferramentas.**

## Hipótese e origem técnica

A biblioteca atual `pathguard` utiliza `open(..., O_NOFOLLOW)`,
`fstat` e compara `st_dev`. Isso **não** cobre bind mounts dentro do
mesmo dispositivo, e verifica componentes do caminho em várias chamadas
(uma possível janela TOCTOU).

O Linux fornece `openat2(2)` (desde 5.6), com restrições de resolução
aplicadas pelo kernel em uma única chamada:

- `RESOLVE_BENEATH`: impede sair de um `dirfd` por componentes do caminho.
- `RESOLVE_NO_SYMLINKS` e `RESOLVE_NO_MAGICLINKS`: recusam symlinks e
  magic-links.
- `RESOLVE_NO_XDEV`: recusa atravessar pontos de montagem, **incluindo
  bind mounts mesmo que usem o mesmo dispositivo**.
- A syscall pode retornar `ENOSYS` (ausente), `EPERM` (policy/seccomp),
  `EINVAL` (não suportada/inválida); o módulo **recusa** sem fallback.
- Número da syscall 437 nas duas famílias de arquitetura atendidas
  (`x86_64` e `aarch64`).

Referências públicas:
- https://man7.org/linux/man-pages/man2/openat2.2.html
- https://github.com/torvalds/linux/blob/master/include/uapi/asm-generic/unistd.h
- https://docs.python.org/3/library/ctypes.html

## Implementação (sem habilitação automática)

`integrations/isolation/linux_openat2_guard.py`:

- Biblioteca **experimental**, Python 3.11+ stdlib com `ctypes` para
  `syscall(437,..., struct open_how)` e todos os quatro `RESOLVE_*`
  acima, sem shell, rede ou operações de escrita.
- `read_bytes/read_text` limitados a 65536 bytes e `list_dir` limitada
  a 1024 nomes; recusa caminhos inválidos, symlinks, arquivos especiais,
  hardlinks detectados por `st_nlink != 1` e mudanças de dispositivo.
  Leituras regulares podem ser curtas: o guard continua lendo até EOF,
  sem ultrapassar `max_bytes + 1` bytes, e recusa crescimento acima do limite.
- Requer `root_fd` de diretório previamente aberto e validado pelo
  coordenador confiável, com `pathguard.open_root` após aprovação de
  configuração. **NÃO estabelece sozinho a proveniência do FD**.
- `openat2` protege a resolução individual de caminhos contra travessia,
  symlinks e mounts. Isso não elimina TOCTOU sobre o conteúdo/inode
  depois de aberto, corrupção por processos externos ou substituição
  da árvore autorizada antes da abertura do `root_fd`.
- A regra de hardlinks `st_nlink` **não protege** contra uma criação/
  remoção concorrente de links. Não permite habilitar `Read/Edit` nativos.

`integrations/isolation/srt_openat2_probe.py`:

- Interface CLI aceita **somente** `--synthetic-only` (opcional `--json`).
- Reutiliza `srt_readonly_pilot` e `srt_launcher` para criar uma
  fixture 0700 nova, com dados e marcadores fictícios, e uma política
  SRT que nega escrita e rede.
- Copia o novo módulo (somente texto versionado) na árvore descartável,
  cria symlink e hardlink **fictícios** para marcador decoy na mesma
  fixture e executa um worker Python fixo pelo SRT, nunca um agente.
- Verifica leitura e listagem autorizadas, bloqueio de symlink, hardlink,
  traversal, caminho absoluto, leitura externa **nativa** pelo sandbox e
  criação nativa de arquivo novo. Todos os controles são obrigatórios;
  ausência de resposta/timeout/nonce incorreto resultam em falha.
- `bind_mount_test = NOT_TESTED_REQUIRES_ISOLATED_MOUNT_NAMESPACE`.
  **Não cria bind mount**, não chama `mount`, `unshare`, `sudo`,
  `nsenter` ou altera mount namespaces existentes. O comportamento
  em bind mounts reais precisará de um fixture isolado aprovado em
  etapa própria.
- Mesmo com sucesso: `strong = UNAVAILABLE`,
  `file_operations = BLOCKED_FOR_AGENTS` e
  `agent_execution_authorized = false`.

## Limites / ameaças residuais

1. **Acesso nativo por hardlink:** o SRT 0.0.81 ainda pode revelar marcador
   fictício pelo hardlink quando o processo usa `open()` nativo, ignorando
   nosso guard; PR #19 reproduziu isso.
2. **Bind mounts:** a flag do kernel é documentada; um teste real em
   namespace isolado **não foi feito**. Sem alegar correção sistêmica.
3. **TOCTOU:** abertura de caminho individual via kernel reduz uma janela
   de resolução, mas `fstat`/leitura e alteração concorrente de conteúdo
   continuam possíveis.
4. **FD autorizado:** `openat2` não sabe se o `root_fd` recebido veio de
   `pathguard.open_root` sobre a pasta explicitamente aprovada.
5. **SRT:** versão fixada 0.0.81; syscall pode ser bloqueada por seccomp.
   Caso isso ocorra, é uma reprovação fail-closed, sem mudar a política
   de SRT nem instalar componentes.
6. **Ferramentas Claude/Read/Edit, MCP, credenciais, acesso real, múltiplos
   agentes/worktrees, outras plataformas:** não abrangidos.
7. **Sem verificação de integridade de conteúdo concorrente:** não supor
   imutabilidade de arquivos que outros processos possam editar.

## Testes e gates

- `test_linux_openat2_guard.py`: 19 testes de syscall real (quando suportada),
  validação, flags/erros, symlinks, hardlinks, limites, FDs e negações.
  Quatro regressões adicionais cobrem leituras curtas, UTF-8 segmentado,
  crescimento posterior ao `fstat` e erro depois de leitura parcial.
  Se syscall indisponível no host de teste, casos dependentes dela são
  **SKIP**, nunca computados como prova de funcionamento.
- `test_srt_openat2_probe.py`: 10 testes de fixture, contrato fechado,
  fake SRT (deve reprovar), nonce, timeout, resultado malformado e gates.
- Não altera `pathguard.py`, `readonly_executor.py`, `srt_launcher.py`,
  `srt_readonly_pilot.py`, `toolkit_doctor.py`, `.claude/` ou agentes.

No checkout da branch no Arch/Fish:

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_linux_openat2_guard.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_srt_openat2_probe.py' -v
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
```

**Somente após verificar origem e testes**, o operador pode executar
o novo canário com dados sintéticos:

```fish
python3 integrations/isolation/srt_openat2_probe.py --synthetic-only --json
echo "Código de saída: $status"
```

Código 0 significa **somente** que os canários obrigatórios funcionaram
naquele runtime. Espera-se `bind_mount_test=NOT_TESTED_...` em todo caso.
Não é autorizado lançar agentes; não usar dados pessoais ou projetos reais.

**Primeira auditoria Codex no HEAD `51f7528` (24/10/2026):** 1 achado P2:
  uma chamada única a `os.read` podia retornar só um prefixo do arquivo.
  Correção aplicada: leitura incremental até EOF/limite, com testes extras.
  Reteste local e nova auditoria independente ainda são necessários.

**Antes de eventual merge:** novos testes Arch (com contagem de SKIP), canário
real SRT no HEAD corrigido, segunda auditoria Codex e revisão humana. Merge apenas com
nova autorização explícita.
