# GH-F1.14 — Snapshot sintético de inode independente sob SRT read-only

**Status: experimento em Draft PR. Nenhuma autorização de agentes, nenhum STRONG.** O objetivo é demonstrar, em ambiente fictício, **uma mitigação de staging** contra hardlinks preexistentes: um processo não deve receber como diretório de trabalho uma árvore com hardlinks para arquivos externos, mesmo quando o guard de caminhos os rejeitaria.

## Motivação

A GH-F1.13 identificou o paradoxo: controles SRT positivos coexistiam com `NATIVE_HARDLINK_LEAK_REPRODUCED`. Um hardlink referencia o **mesmo inode** do arquivo de origem e permite que `open()` nativo o leia por outro nome, sem passar por `pathguard`. Consequentemente, apenas prometer que a IA usará um guard não impede esse desvio.

Documentação do Linux consultada:
- https://man7.org/linux/man-pages/man7/symlink.7.html — semântica de hardlinks/inodes.
- https://man7.org/linux/man-pages/man2/openat2.2.html — flags `RESOLVE_BENEATH`, `RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS`, `RESOLVE_NO_XDEV` (inclui bind mounts).

## Solução sob teste (apenas fixture nova)

`integrations/isolation/srt_snapshot_pilot.py` não possui entrada de projeto real, caminho de usuário, comando arbitrário nem lista configurável de arquivos. A CLI aceita **apenas `--synthetic-only [--json]`**. Ela:

1. Chama exclusivamente `srt_launcher.create_fixture()`, que cria uma árvore temporária 0700 com marcadores fictícios e uma **origem contaminada** por hardlink/symlink para um decoy fora da pasta autorizada.
2. Confere que o hardlink de prova existe e aponta para o inode externo fictício; se não existe, **reprova**, em vez de fingir que o cenário foi coberto.
3. Abre a raiz da origem sintética via `pathguard.open_root`. O guard `linux_openat2_guard.read_bytes` deve **rejeitar o hardlink e o symlink**. Ele lê somente `canary_read.txt`, até 64 KiB, com `RESOLVE_NO_XDEV` e as demais flags. Nenhum `open()` simples é utilizado para leitura dessa fonte.
4. Cria `snapshot-synthetic/sample.txt` via `O_EXCL | O_NOFOLLOW` e **copia bytes**, nunca usa `os.link`, `rename`, bind mount ou reflink. Exige `st_nlink == 1`, inode destino independente e um único arquivo no snapshot. Marca o arquivo 0400 e a pasta 0500.
5. Reaproveita a política SRT read-only verificada (`denyRead=["/"]`, `allowRead` apenas no **snapshot** e runtime mínimo, `allowWrite=[]`, rede deny, namespaces fracos desativados). Não modifica configuração permanente de nenhum componente.
6. Executa **somente um worker Python constante** sob SRT, que tenta `open()` nativo: leitura autorizada do snapshot (deve funcionar), leitura do original, hardlink, symlink e decoy externo (devem falhar); criação e truncamento na cópia (devem falhar); listagem da pasta (deve conter apenas `sample.txt`).
7. O supervisor confere o conteúdo da cópia e do decoy após o processo, verifica inode e ausência de arquivos extras, lendo o snapshot por `openat2` (não seguindo symlink trocado). Um SRT de mentira que apenas encaminhe comandos **deve reprovar**.
8. Restaura permissões da pasta sintética para limpeza e descarta a fixture ao encerrar. Não executa `sudo`, `mount`, `unshare` ou `nsenter`.

Os métodos `stage_snapshot`, `seal_snapshot` e `host_snapshot_intact` são auxiliares **apenas desta prova**, não uma API pública de staging para projetos reais, não revalidam identidade de usuários ou aprovações e não devem ser conectados a agentes.

## Interpretação dos resultados

O piloto retorna `exit_code=0` **somente quando os 12 checks deste cenário passam**: snapshot de inode novo, política read-only validada, integridade no host, worker executado e oito observações de I/O nativo. O status de prontidão é **sempre `readiness=BLOCKED` e `strong=UNAVAILABLE`**, mesmo que os 12 checks passem. As flags de execução, operações reais, provedores, transferência de dados e isolamento nativo para agentes permanecem `false`.

Se kernel/`openat2` não estiver disponível, hardlink do fixture não puder ser criado, SRT 0.0.81 não estiver operacional, configurações divergirem, o processo falhar, ou qualquer leitura externa for permitida, o piloto retorna **2** e reprova. **Um PASS não altera a GH-F1.13**, que continua reportando o vazamento na árvore não copiada.

## Limitações ainda bloqueantes

- A demonstração usa **um arquivo pequeno fictício**, copiado antes do acesso do worker. Não suporta diretórios grandes, binários arbitrários, milhares de caminhos, nem dados reais.
- Uma etapa de confiança externa ainda terá que demonstrar a **proveniência do root_fd** e integridade de origem/escopo. `st_nlink` e estatísticas antes/depois não eliminam TOCTOU quando outra pessoa modifica a origem simultaneamente.
- Uma cópia isolada reduz o risco de links antigos serem expostos ao processo, mas **não prova que as ferramentas nativas reais do Claude/Codex, extensões, hooks ou plugins** fiquem confinados; o worker é Python fixo.
- Bind mounts reais não foram exercitados dentro de namespace descartável; `RESOLVE_NO_XDEV` é uma mitigação de *path lookup*, não isolamento de processo por si só.
- O SRT permite leituras mínimas do runtime (`/usr` e dependências exatas) que deverão ser avaliadas de forma independente. Nenhuma concessão de cloud fallback, network ou credenciais.
- A exploração de hardlinks pré-existentes na origem intencionalmente persiste na GH-F1.13 para diagnóstico; o presente piloto testa a mitigação por **não incluir esses links na árvore exposta**, não corrige diretamente a configuração global do SRT.

## Testes no Arch (Fish)

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_srt_snapshot_pilot.py' -v
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

**Contagens esperadas, não verificadas no Arch**: 37 testes novos, 188 gerais inalterados, **256 de isolamento** (219 existentes +37). Alguns casos dependentes do kernel podem ser `SKIP` fora do Arch; `SKIP` não é evidência positiva.

Após o unit test, o operador pode optar por executar este piloto SRT sintético real:

```fish
python3 integrations/isolation/srt_snapshot_pilot.py --synthetic-only --json
echo "Código do piloto sintético: $status"
```

Neste comando, **código 0 seria sucesso do ensaio específico**, sem autorizar agentes. Código 2 indicaria falha ou prova inconclusiva e exigiria investigação. A GH-F1.13 continuará corretamente em BLOCKED/2, independentemente do resultado aqui.

## Gates antes do merge

- Evidência dos testes no Arch, **resultado e lista dos 12 checks do piloto SRT**, integridade do Git e SHA revisada.
- Auditoria Codex GPT-6 High com `--sandbox read-only`, no head exato, sem usar o ambiente read-only como prova da suíte que precisa de pasta temporária.
- Correção de P1/P2, reteste e nova auditoria quando necessário.
- **Autorização humana exclusiva para este PR**, sem reutilizar permissão de PR anterior.
- Nenhuma ativação de agente, orquestrador, UI ou mudança em `.claude/`, `agents/`, `integrations/isolation/toolkit_doctor.py`, `native_boundary_readiness.py`, SRT original ou GH-F1.10–12.
