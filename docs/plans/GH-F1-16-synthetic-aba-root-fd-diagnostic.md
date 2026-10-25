# GH-F1.16 — Diagnóstico sintético de ataques ABA e vínculo do root_fd

**Estado:** experimento em Draft PR. **Não é mitigação nem autoridade de execução.** Uso exclusivamente de `srt_launcher.create_fixture()` (arquivos fictícios descartáveis); mantém `STRONG=UNAVAILABLE`, `readiness=BLOCKED` e todas as autorizações de agentes, arquivos reais, nuvem e transferência em `false`.

## Motivação

Na GH-F1.15, `srt_snapshot_pilot.stage_snapshot()` passou a fazer duas leituras guardadas (`openat2`) e comparar os bytes. Essa alteração detectou os **cinco interleavings cooperativos** de concorrência existentes, mas não prova proteção contra ataques ABA.

**ABA** aqui significa `A → B → A`: outro processo/thread modifica o arquivo **depois da primeira leitura** e restaura exatamente os mesmos bytes **antes da segunda leitura**. No fim, `st_dev`, `st_ino` e `st_size` podem permanecer iguais, assim como os bytes observados em ambas as leituras. O arquivo pode, portanto, **ter sido alterado durante o estágio e ainda assim o estágio ser aceito**. Timestamp ou comparação reiterada não estabelece atomicidade.

Outra lacuna é a **proveniência do `root_fd`**. Um descritor aberto permanece referenciando o diretório original mesmo depois de o nome da pasta ter sido substituído, e um descritor de outro diretório pode ser repassado por engano. Uma comparação imediata de `fstat(fd)` com `stat(path, follow_symlinks=False)` identifica algumas discrepâncias, mas não confirma que um proprietário confiável concedeu acesso nem impede rebind posterior, bind mount ou corrida entre verificações.

## O que foi adicionado (diagnóstico, sem alterar a GH-F1.14/15)

`integrations/isolation/synthetic_aba_root_fd_probe.py`: CLI **fechada `--synthetic-only [--json]`**, sem caminhos de entrada, sem comandos de usuário, sem subprocessos, sem SRT e sem agents. Executa **quatro cenários** em fixtures novas:

| Caso | Observação buscada | Interpretação |
|---|---|---|
| `root_fd_baseline` | `BOUND` | FD aberto e nome coincidem na fixture **naquele momento** |
| `root_fd_foreign` | `REJECTED` | FD de outra pasta fictícia não coincide com o nome autorizado |
| `root_fd_replaced_path` | `STALE_FD_DETECTED` | Pasta fictícia renomeada/substituída; FD antigo **ainda lê** a árvore antiga, mas não corresponde mais ao caminho |
| `aba_reverted_between_reads` | `ABA_UNDETECTED` | Uma thread escreve bytes diferentes, restaura os originais entre leituras e o `stage_snapshot` **aceita** a cópia; evidencia o bypass da verificação dupla |

A thread ABA tem sincronização `threading.Event` e timeout; o caso só é observado se a mutação intermediária de fato aconteceu, a restauração foi confirmada, ocorreram pelo menos duas leituras e a cópia aceita permaneceu íntegra. Alterações ocorrem **somente** em `fx.auth_canary`; o diretório de origem nomeado e qualquer `root_fd` testado derivam da fixture recém-criada. Não se utilizam arquivos dos projetos Solenne/FIINA/Velaris ou de qualquer workspace real.

As rotinas auxiliares e a comparação de identidade são **internas ao diagnóstico**, não devem ser reutilizadas como guard confiável de autorização. Os documentos e o código existente de orquestração, permissions, doctor, SRT, readiness e agentes permanecem intactos.

## Como interpretar um resultado

O comando retorna **sempre código de saída 2**, incluindo quando os quatro cenários mostram as observações esperadas. Em particular, `ABA_UNDETECTED` é um **bloqueador real comprovado no cenário**, não `PASS` de segurança. O relatório sempre contém:

- `strong: "UNAVAILABLE"` e `readiness: "BLOCKED"`.
- `agent_execution_authorized: false`, `file_operations_authorized: false`, `cloud_call_authorized: false`, `data_transfer_authorized: false`.
- `root_fd_owner_provenance_verified: false` e `aba_protection_proven: false`.
- `real_bind_mount_tested: false`, `real_worktree_verified: false`, `native_tools_isolated_for_agents: false`, `srt_runtime_revalidated: false`.
- Razão `ABA_UNDETECTED_REPRODUCED` quando o cenário de mutação e restauração foi de fato reproduzido.
- `NOT_VERIFIED` e `SYNTHETIC_EVIDENCE_INCOMPLETE` quando faltam evidências, sem transformar ausência de reprodução em garantia de segurança.

O experimento **não modifica** `srt_snapshot_pilot.py`: ele demonstra uma limitação, não oferece uma mitigação parcial enganosa. Para uso futuro real seria necessário um protocolo comprovado de ownership e proveniência, snapshot/freeze/imutabilidade durante staging, controle de escritores e isolamento que não permita contornar o guard com ferramentas nativas. Exigir consentimento humano específico de cada PR.

## Validação no Arch Linux (Fish)

```fish
python3 -I -m unittest discover -s integrations/isolation -p 'test_synthetic_aba_root_fd_probe.py' -v
python3 -I -m unittest discover -s tests -p 'test_*.py'
python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
git diff --check main...HEAD
git status --short
```

Contagens **esperadas e ainda não testadas no Arch**: **30 testes novos**, **188 gerais**, **316 de isolamento** (286 existentes após GH-F1.15 +30). Nenhum `SKIP` de kernel pode ser tratado como evidência positiva.

**Diagnóstico separado:** não acoplar à cadeia `and` que exige exit 0, pois exit 2 é **esperado**.

```fish
python3 integrations/isolation/synthetic_aba_root_fd_probe.py --synthetic-only --json
echo "Código do diagnóstico: $status"
```

Esperado: `BOUND`, `REJECTED`, `STALE_FD_DETECTED` e `ABA_UNDETECTED`, com código **2**, `readiness=BLOCKED`, agentes desautorizados. Se houver `NOT_VERIFIED`, analisar a causa (kernel, fixture ou canário) sem ignorar o blocker.

## Limites e gates de revisão

- Nada de execução real de agentes, hook de filesystem, cloud fallback, `sudo`, `mount`, `unshare`, `nsenter`, arquivos reais ou alterações permanentes.
- **Não** se deve inferir que a comparação de diretório via `fstat`+ `stat` é uma cadeia de confiança completa: ela pode mudar no instante seguinte e não autentica o proprietário.
- Mesmo ataques ABA não reproduzidos em outro host permanecem fora das garantias; não se habilita `STRONG` por mera ausência de observação.
- Conferir **4 arquivos esperados**: novo módulo, novos testes, este documento e índice. Sem mudança de código já integrado da GH-F1.14/15.
- Exigir unit tests no Arch, diagnóstico com sua saída, integridade do Git, auditoria Codex GPT-6 High read-only, correção de P1/P2 quando encontrados.
- **Merge só após autorização humana explícita para o PR exato**. O PR histórico #9 permanece em Draft.
