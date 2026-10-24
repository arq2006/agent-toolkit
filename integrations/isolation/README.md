# integrations/isolation — config, guarda de caminhos, launcher SRT e doctor (GH-F1.8, PR2–PR3)

Status: **proposta em implementação inicial** ([ADR-011](../../docs/adr/ADR-011-isolamento-do-processo.md)).
Requisito: **Python 3.11+**, só biblioteca padrão. Nenhuma dependência, rede ou shell.

- `isolation_config.py`: lê o TOML de configuração (pasta autorizada, autenticação, rede) com
  validação estrita (abertura não bloqueante: só arquivo regular). Ausente ou inválido, recusa;
  `network.allow` existe somente com `mode = "allowlist"`. Exemplo em `examples/toolkit.example.toml`.
- `pathguard.py`: valida caminhos relativos e opera sob a pasta autorizada com `dir_fd`,
  `O_NOFOLLOW` e `fstat`; recusa absolutos, `..`, NUL, symlinks, arquivos não regulares e
  hardlinks. A pasta autorizada é aberta componente a componente (`dir_fd` + `O_NOFOLLOW`) e
  nunca pode ser `/`, a home da conta (lida do banco de contas do SO, não da variável `HOME`) nem
  ancestral dela.

**Isto não é isolamento.** O `pathguard` protege só operações feitas por ele (o futuro executor).
Não protege agentes com Read/Edit nativos nem substitui srt/bubblewrap; não elimina TOCTOU contra
processos externos, nem detecta bind mounts, hardlinks criados após a checagem ou troca concorrente
de diretórios ancestrais por quem tenha escrita neles.

Testes (diretórios temporários fictícios): `python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'`

## PR3: launcher SRT e doctor (diagnóstico; não libera agentes)

- `srt_launcher.py`: detecta (nunca instala) `srt` **exatamente 0.0.81**, `node`, `bwrap` (>= 0.8.0; só 0.12.0 foi
  exercitada), `socat` e `rg`; gera a política `--settings` (leitura negada em `/`, exceções mínimas e justificadas do
  runtime: `/usr`, `/etc/ld.so.cache` e o arquivo EXATO `vendor/seccomp/<arch>/apply-seccomp` do pacote do srt, que pode
  estar fora de `/usr` (ex.: `~/.local/lib/node_modules`); nunca o pacote, `~/.local` ou `/home`, e seccomp segue ativo; escrita só na pasta autorizada; rede em deny total, inclusive loopback do host);
  ambiente do processo construído do zero (sem credenciais, `SSH_AUTH_SOCK`, proxies, `LD_PRELOAD`...), home fictícia,
  `subprocess` sem shell, timeout com encerramento do grupo de processos. Não há API para comandos arbitrários: só os
  canários internos, e só sobre um fixture sintético descartável. `network.mode = "allowlist"` é recusado. Qualquer erro
  recusa; não existe execução sem `srt` nem sem `--settings`.
- `toolkit_doctor.py`: roda os canários no fixture (nunca na sua pasta; a pasta da config é só validada) e imprime resumo
  ou JSON com checks, motivos e limitações. Cada "bloqueado" só vale com controle positivo bem-sucedido no mesmo run.

```
python3 integrations/isolation/toolkit_doctor.py --config /caminho/toolkit.toml [--json]
```

Saída: `0` canários obrigatórios passaram, `2` falha ou teste incompleto, `3` config inválida/plataforma não suportada.
**Código 0 não autoriza nada**: nesta etapa `STRONG` é indisponível, operações com arquivos ficam `BLOCKED` e
`agent_execution_authorized` é sempre `false`. Hardlinks, TOCTOU, bind mounts e Read/Edit nativos seguem sem mitigação
comprovada. Dependências no Arch: `pacman -S bubblewrap socat ripgrep nodejs` e `npm i -g @anthropic-ai/sandbox-runtime@0.0.81`
(instalação por sua conta; o toolkit não instala). Só Linux foi exercitado; WSL2/macOS/Windows sem validação.

Os testes usam `srt` falso (`fakes.py`) apenas para a lógica e para provar que um sandbox que não isola é reprovado;
não são evidência de isolamento. Evidência real só vem do doctor em máquina com bwrap/srt.

Classificação do doctor (correção pós-teste no Arch): `fail_closed_*` só dá PASS com controle positivo funcional do sandbox
**e** a mensagem específica de recusa de política do srt (código 1, "Refusing to run with the built-in defaults", citando o
arquivo); falha genérica (ex.: 127) fica NOT_TESTED. `runtime_reads` só dá PASS se o canário positivo rodou. Quando o
canário falha por `apply-seccomp`, o doctor diferencia "ausente fisicamente" de "oculto dentro do sandbox".
