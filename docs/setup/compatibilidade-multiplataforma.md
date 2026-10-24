# Compatibilidade multiplataforma, GitHub e sincronização (GH-F1.5)

Status: **auditoria e proposta; nenhuma alteração funcional foi feita** no gerador nem nos testes. Qualquer mudança em `integrations/claude-code/materialize.py` ou `test_materialize.py` exige **autorização separada** de Arthur. Guias: [Arch Linux](arch-linux.md), [Windows](windows.md).

## 1. Princípio: um toolkit, dois computadores
Um único repositório ([arq2006/agent-toolkit](https://github.com/arq2006/agent-toolkit)); mesmos `agents/`, `integrations/claude-code/mapping.yaml`, contratos e critérios de teste em Linux e Windows. O que difere é só o **ambiente isolado** (conta/VM/WSL) e a **sintaxe de shell** dos roteiros. Nada de arquivos ou ramos específicos por máquina.

## 2. Auditoria de portabilidade (código atual, sem executá-lo no Windows)
Leitura de `materialize.py`, `test_materialize.py`, `mapping.yaml` e `.claude/agents/` na `main` (`a9e4150`). Situações no Windows: **quebra seguro** = falha com erro, sem gravar; **degrada** = roda com garantia menor; **ok**.

| # | Ponto | Onde | Linux | Windows | Alternativa portável proposta (sem reduzir a segurança) |
|---|---|---|---|---|---|
| 1 | `sha256sum -c` via `subprocess` | `git_state` | ok | quebra seguro (`FileNotFoundError` encerra `git-state`); só existe no Git Bash | subcomando `checksums` em Python (`hashlib` lendo `docs/CHECKSUMS.sha256`, formato `hash  caminho`), usado por `git-state` e pelos guias; mesmo resultado nos dois SOs |
| 2 | Permissões POSIX do diretório do snapshot (`st_mode & 0o077`) e modo `0o600` | `write_snapshot` | ok | quebra seguro (bits de modo não refletem ACLs; o teste acusa "aberto") | no Windows, criar o diretório pelo próprio comando (`tempfile.mkdtemp`, a confirmar se restringe a ACL ao usuário na versão usada) e verificar a ACL (`icacls` ou `win32security`); manter a verificação POSIX no Linux |
| 3 | `O_NOFOLLOW` via `getattr(..., 0)` | `write_new`, `write_snapshot` | ok | degrada (sem a flag; resta a checagem `is_symlink` anterior, sujeita a corrida) | tratar no Windows a corrida com verificação posterior ao `open` e recusa em caso de reparse point |
| 4 | Links simbólicos e **junções** (`Path.is_symlink`) | `symlink_free`, `dest_errors` | ok | **degrada**: junção de diretório não é `is_symlink`; links simbólicos exigem privilégio ou Modo Desenvolvedor | detectar *reparse points* (`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`, ou `os.path.isjunction` quando disponível) e recusá-los |
| 5 | `os.link` para criar sem sobrescrever | `write_new` | ok | NTFS ok; FAT/exFAT/alguns compartilhamentos falham (erro, rollback) | no Windows, `os.rename` falha se o destino existe (semântica oposta à POSIX), preservando a regra "nunca sobrescreve"; manter `os.link` no POSIX |
| 6 | **Codificação**: `read_text()`/`write_text()`/`fdopen(...,"w")` sem `encoding` | vários | UTF-8 do locale | **quebra ou corrompe** acentos (cp1252 por padrão em versões antigas) | `encoding="utf-8"` explícito em toda leitura/escrita |
| 7 | **Quebra de linha**: modo texto grava CRLF no Windows | `write_new`, `write_snapshot` | LF | gera arquivos CRLF (bytes diferentes dos do repositório) | `newline="\n"` ao abrir; arquivos gerados byte a byte idênticos nos dois SOs |
| 8 | Git `autocrlf` e **checksums** | repositório (sem `.gitattributes`) | ok | **risco**: checkout com CRLF altera os bytes de `docs/references/`, `docs/security/` e `CHECKSUMS.sha256` e quebra os checksums | adicionar `.gitattributes` (`* text=auto eol=lf`, `*.pdf binary`, protegidos `-text`) — arquivo novo na raiz, **requer autorização** |
| 9 | `python3 -I` nos comandos | guias/docs | ok | `python3` costuma não existir (alias da Store); usar `py -3 -I` | documentar os dois; sem mudança no código |
| 10 | Mensagem citando `umask 077; mktemp -d` | `write_snapshot` | ok | cosmético | texto neutro: "diretório privado do usuário" |
| 11 | PyYAML (`import yaml`) | `materialize.py`, testes | pacote `python-yaml` | `pip install pyyaml` (instalação a aprovar) | verificar com `python -c "import yaml"`; sem alternativa em biblioteca padrão |
| 12 | Testes: `symlink_to`, `0o700/0o600/0o755`, `os.chmod` | `test_materialize.py` | ok | `symlink_to` falha sem privilégio; asserts POSIX falham | trocar por testes de junção (`mklink /J`) e de ACL no Windows; `skip` **com motivo explícito** só para o que for impossível, nunca passar em silêncio |
| 13 | `GIT_CONFIG_GLOBAL=os.devnull` nos testes | `GitState` | ok | `os.devnull` vira `nul`, aceito pelo Git for Windows (a confirmar) | manter; validar |
| 14 | Remoção do diretório temporário com `.git` somente leitura | testes | ok | pode falhar em limpeza | manter `TemporaryDirectory`; tratar `PermissionError` na limpeza |
| 15 | `mapping.yaml` e `.claude/agents/*.md` | dados | ok | **ok**: sem caminhos de máquina, links relativos com `/`, LF | nenhuma; só o item 8 garante LF no checkout |
| 16 | Instruções dos agentes citam `sha256sum` | `agents/*/AGENT.md` | ok | planner/auditor não têm Bash; o invocador roda o preflight | usar o subcomando `checksums` (item 1) nos guias |

Resumo: o gerador **falha de forma segura** no Windows (itens 1, 2, 6) e tem **três degradações de segurança** a corrigir antes de gravar lá (3, 4, 7/8). Não afirmo compatibilidade: está **não validada**.

**Decisão registrada (22/10/2026):** a portabilidade **nativa** do gerador para Windows exige uma **etapa separada de implementação e testes** (alterações em `materialize.py`/`test_materialize.py`, `.gitattributes`, validação nos dois sistemas), sujeita a autorização própria. Enquanto ela não for feita e validada, o piloto no Windows deve rodar dentro de VM/convidado Linux, e nenhuma afirmação de compatibilidade nativa vale.

## 3. Como validar a mesma implementação nos dois SOs (proposta, após autorização das mudanças)
1. Mesma revisão (`git rev-parse HEAD` idêntico) e Python ≥ versão mínima registrada no PR; PyYAML presente.
2. `python -I integrations/claude-code/test_materialize.py` (Windows: `py -3 -I …`): resultados esperados iguais; **skips listados com motivo**; nenhum teste pode passar por ter sido ignorado.
3. Testes de falha em ambos: dry-run sem gravar; divergente recusado; ferramenta extra rejeitada; nomes inválidos; links simbólicos **e junções** (Windows); diretório do snapshot aberto recusado (POSIX: modo; Windows: ACL); falha de I/O simulada com rollback; falha do Git tratada como erro.
4. Equivalência dos artefatos: `materialize.py agents` deve informar "sem mudanças" nos dois SOs; comparar o SHA-256 de `.claude/agents/planner.md` e `auditor.md` entre as máquinas.
5. Permissões: guias de setup §5 (Linux: `id`, `sudo -n`, canário; Windows: `icacls`, `whoami /groups`, canário) com as mesmas condições de parada.
6. `checksums` (proposto) retorna o mesmo resultado que `sha256sum -c` no Linux, e o Windows o replica.
Registrar cada execução (SO, versão do Python, `claude --version`, saída) no PR correspondente.

## 4. Um repositório GitHub, dois clones
- **Toolkit** = `arq2006/agent-toolkit` (público, versionado). **Sandbox de teste** = repositório Git **descartável**, local, sem remoto, dados fictícios, fora do clone do toolkit; nunca versionado nem publicado.
- Cada máquina tem **o seu clone**. Alterações só por **branch + PR** e integração aprovada; as demais máquinas fazem `git fetch` e `git pull --ff-only` depois do merge aprovado (branches e mensagens em inglês).
- **Não sincronizar:** sandboxes, snapshots, evidências, `~/.claude`, credenciais, tokens, chaves SSH, arquivos temporários. Não copiar configuração de autenticação entre computadores: cada máquina autentica separadamente (Git Credential Manager/`gh auth` e login do Claude Code próprios).
- **Proibido:** `push --force`, `reset --hard`, `clean`, rebase destrutivo e merge automático (CLAUDE.md). Em conflito, parar e pedir decisão.
- Fins de linha e checksums dependem do `.gitattributes` proposto (item 8); até a autorização, no Windows configure `core.autocrlf=false` no clone do toolkit.
- Caminhos nos documentos: variáveis (`$HOME`, `$env:USERPROFILE`), sem nome de usuário nem letra de unidade.

## 5. Ações que exigem autorização separada
1. Criar conta Linux/Windows, `sudo`, instalar pacotes, alterar permissões/ACLs, criar o sandbox, ativar Remote Control: **nada feito**.
2. Mudar o caminho do sandbox Linux para a home da conta dedicada (proposta no guia Arch).
3. Alterar `materialize.py`/`test_materialize.py` (itens 1–7, 10, 12–14) e criar `.gitattributes` (item 8).
4. Qualquer teste no Windows.
