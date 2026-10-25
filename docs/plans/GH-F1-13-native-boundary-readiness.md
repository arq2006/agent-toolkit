# GH-F1.13 — Gate de prontidão para leitura nativa (hardlinks, mounts, concorrência)

**Status:** proposta em Draft PR; diagnóstico restritivo, **não** correção completa nem permissão para executar agentes. Continua `STRONG=UNAVAILABLE`.

## Problema concreto

O experimento `srt_readonly_pilot.py` pode aprovar seus controles existentes (`exit_code=0`) e, simultaneamente, registrar `native_hardlink_limitation=NATIVE_HARDLINK_LEAK_REPRODUCED`: um processo dentro do SRT conseguiu ler um arquivo fictício fora da raiz por meio de um **hardlink dentro da área liberada**. O `pathguard` e o `linux_openat2_guard` rejeitam esse link via `st_nlink`, mas **Read/Edit nativos e chamadas `open()` arbitrárias não são forçadas a utilizar os guards**. Portanto, código zero no piloto existente **não** comprova que a fronteira de leitura de um agente seja segura.

O segundo canário `srt_openat2_probe.py` exerce `RESOLVE_NO_XDEV`, mas relata `bind_mount_test=NOT_TESTED_REQUIRES_ISOLATED_MOUNT_NAMESPACE`; até aqui nenhum teste real isolado de bind mount foi realizado.

## Entrega (sem modificar os pilotos existentes)

- `integrations/isolation/native_boundary_readiness.py`: `assess_reports(readonly, openat2)`, avaliador **puramente em memória** que aceita somente um conjunto completo e sem duplicatas dos checks existentes, com tipos e campos de não autorização esperados. Usa os resultados existentes como **evidência não confiável** e jamais como concessão.
- `run_synthetic()`: chama **exclusivamente os dois pilotos de fixture já existentes**, sem receber argumentos de usuário nem caminhos reais, agentes, scripts, tokens ou comandos. Somente via `--synthetic-only [--json]`.
- `integrations/isolation/test_native_boundary_readiness.py`: **30 regressões**, com outputs simulados; nunca dispara SRT real durante a suíte unittest.
- Esta documentação e link no índice `docs/README.md`.

### Política de classificação

- **Obrigatório:** cada um dos 15 checks do piloto somente leitura e dos 9 checks `openat2` deve ter `PASS` sem duplicata, o processo precisa reportar `exit_code=0`, `strong=UNAVAILABLE`, `file_operations=BLOCKED_FOR_AGENTS` e `agent_execution_authorized=false`. Relatório ausente, incompleto, forjado ou contraditório reprova.
- Se o canário existente observou `NATIVE_HARDLINK_LEAK_REPRODUCED`, registrar esse **bloqueador explícito**, mesmo com todos os checks anteriores em PASS.
- Se houve `NATIVE_READ_NOT_OBSERVED`, o diagnóstico não assume que todas as ferramentas nativas estão isoladas: `NATIVE_HARDLINK_DENIAL_NOT_PROVEN`.
- Se resultado de hardlink está ausente ou inesperado: `NATIVE_HARDLINK_TEST_INCOMPLETE`.
- Se o resultado de bind mount difere do conhecido `NOT_TESTED...`, registrar `BIND_MOUNT_REPORT_UNRECOGNIZED`; **nenhum valor textual recebido** pode provar mounts reais.
- Independentemente dos resultados, continuamos sem verificação de bind mounts reais, mutações concorrentes/TOCTOU, ferramentas nativas de agentes, proveniência de `root_fd`, worktrees e aprovações humanas. **Sempre** `readiness=BLOCKED`, `strong=UNAVAILABLE`, `exit_code=2` e todas as flags efetivas `false`.

Esta etapa deliberadamente **não fornece um caminho para retornar `STRONG=AVAILABLE`**. Isso será objeto de um mecanismo de isolamento próprio, com controles positivos/negativos, ambiente descartável seguro e nova autorização. Não substituir o doctor ou acoplar este diagnóstico a tarefas reais.

## Execução opcional no Arch (Fish)

Primeiro, testes estáticos e de fixture já previstos:

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_native_boundary_readiness.py' -v
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

Esperado nesta branch: **30 testes novos**, suíte geral **188** (inalterada), suíte de isolamento **219** (189 integrados + 30), a confirmar no Arch. Saídas `usage: ... error` de testes negativos de argparse são esperadas.

**Diagnóstico de SRT com subprocesso sintético (opt-in explícito):**

```fish
python3 integrations/isolation/native_boundary_readiness.py --synthetic-only --json
echo "Código de saída do diagnóstico: $status"
```

O programa detecta apenas as dependências SRT já presentes e utiliza fixtures descartáveis (sem acesso a projetos reais). **Código `2` é o comportamento esperado e obrigatório** porque a fronteira não foi comprovada; com SRT 0.0.81 o campo `native_hardlink_leak_observed` poderá ficar `true`, evidenciando a lacuna. Ausência de dependências ou falhas também resulta em `2`, com motivos de diagnóstico incompleto. Nenhum caminho de workspace/configuração é aceito na CLI.

Executar o canário não autoriza nenhuma mitigação nem usa privilégios elevados; **não executar mount, unshare, sudo, nsenter ou comandos de modificação do sistema**. Não mostrar nem gravar quaisquer dados/segredos reais nos logs.

## Próximas barreiras técnicas

1. Projetar um isolamento nativo que impeça ler dados fora da fronteira mesmo com hardlink em diretório selecionado; o guard textual não basta.
2. Definir ensaio de bind mounts **somente** dentro de namespace isolado descartável, com procedimento aprovado; nenhum mount é realizado aqui.
3. Validar snapshot imutável/single-link, proveniência da raiz, proteção contra alterações concorrentes e comportamento das ferramentas nativas.
4. Só depois considerar comandos de agentes read-only e integração com coordenação GH-F1.10–12. Qualquer agente real segue desautorizado.

## Gates de revisão

- Testes no Arch para o HEAD fixo, com resultado diferenciado entre unit tests (OK) e diagnóstico (intencionalmente BLOCKED).
- Auditoria independente Codex em read-only; corrigir P1/P2 e repetir testes.
- PR em Draft até aprovação humana explícita para **este PR**; não integrar automaticamente.
- PR #9 e os arquivos históricos/contratos/agentes anteriores permanecem intactos.
