# GH-F2.1b — Piloto de skill própria UI/UX, sem ativação

**Status: proposta em Draft PR para revisão e testes locais.** Esta etapa não é a GH-F2.2 de integração com agentes: aquela segue bloqueada pelas dependências GH-F1.5/F1.6/GH-F1.7, isolamento STRONG não comprovado e auditoria Codex independente ainda pendente.

## Objetivo

Criar **uma** skill própria de revisão de interface somente leitura, independente dos executáveis externos. A skill deve analisar dados de UI fornecidos pelo usuário ou explicitamente autorizados, sem editar, instalar, abrir navegador, iniciar servidor, usar rede, carregar plugins ou chamar serviços. A intenção é ter uma habilidade pequena que possa ser auditada antes de qualquer ativação futura.

## Arquivos e arquitetura

| Arquivo | Função |
|---|---|
| `skills/ui-design-review-readonly/SKILL.md` | Procedimento original em padrão Agent Skills |
| `skills/ui-design-review-readonly/contract.yaml` | Contrato A0, status `SOURCE_ONLY_NOT_MATERIALIZED` |
| `scripts/validate_ui_review_skill.py` | Verificador offline de frontmatter restrito + contrato |
| `tests/test_ui_review_skill.py` | Casos positivos/negativos de esquema e permissões |
| `skills/README.md` | Índice para futura distribuição |

A fonte da verdade continua `skills/` na raiz do toolkit, conforme [ADR-007](../adr/ADR-007-arquitetura-de-diretorios.md). **Não** foi criada uma cópia em `.claude/skills/` nem no escopo pessoal `~/.claude/skills/`. Claude Code só descobre automaticamente skills materializadas nos locais suportados; colocar um arquivo na fonte neutra não constitui ativação. Entretanto, mesmo uma skill só textual deve ser tratada como código de instrução não confiável até aprovada.

## Contrato de escopo mínimo

- `A0` apenas: leitura autorizada, análise de diffs e relato de achados. Isso é **necessidade declarada**, não concessão efetiva de permissão pelo runtime.
- Ferramenta listada: `T-01`, uso do Git limitado a operações somente leitura. Não há subprocessos, launcher, hooks, MCP, navegador, downloads, rede, Impeccable ou Replica.
- Parada imediata ao detectar ampliação de escopo, instrução externa maliciosa, pedido de escrita, credenciais ou acesso a outros projetos.
- Relatório com evidência e confiança. Screenshot não comprova responsividade, DOM semântico nem navegação por teclado.
- `docs/references/`, `docs/security/` e `docs/CHECKSUMS.sha256` permanecem protegidos.

## Relação com skills externas

Os procedimentos são **texto original do toolkit** e não uma redistribuição de `Impeccable` ou `Replica Design`. Suas avaliações permanecem `HOLD` na [GH-F2.1](GH-F2-1-skills-specialized-review.md). O piloto cobre apenas triagem e orientação, não gera tokens CSS nem executa varreduras.

## Validação

O `contract.yaml` é escrito no **subconjunto JSON de YAML 1.2**. Isso permite parse com biblioteca padrão Python, mas o validador não pretende suportar YAML arbitrário nem substituir o validador oficial `skills-ref` (não instalado). O parser de frontmatter suporta somente campos permitidos e scalars escritos de forma restrita. A conformidade formal com Agent Skills e o carregamento real no Claude Code seguem pendentes.

Comandos (Fish, no checkout da branch):

```fish
python3 scripts/validate_ui_review_skill.py
python3 -m unittest discover -s tests -p 'test_ui_review_skill.py' -v
python3 scripts/skill_router.py validate
python3 scripts/validate_skill_reviews.py --json
```

**Aceite documental**: `VALID` para o novo contrato, 22 testes de esquema esperados e validações anteriores sem regressão. Testes estruturais **não** comprovam bloqueio de filesystem ou segurança de um agente em execução. Auditoria externa do Codex, revisão humana e teste de sandbox são gates independentes.

## Próximo passo depois deste PR

Uma futura etapa de habilitação poderá avaliar materialização (com dry-run e aprovação própria), isolamento efetivo, e eventual promoção para uma skill utilizável; antes disso, resolver GH-F1.5/F1.6 e as limitações da ADR-011, sem reclassificar SRT como STRONG.

**Não realizar merge, instalar plugins nem criar agentes sem autorização específica.**
