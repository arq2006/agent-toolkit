# integrations/isolation — configuração e guarda de caminhos (GH-F1.8, PR2)

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
de diretórios ancestrais por quem tenha escrita neles. Não há launcher, `doctor` nem classificação STRONG nesta etapa.

Testes (diretórios temporários fictícios): `python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'`
