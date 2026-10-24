# Biblioteca de skills — GH-F2.0 (catálogo) + GH-F2.1 (revisão de candidatas)

**Status: GH-F2.0 e GH-F2.1 integradas. GH-F2.1b propõe a primeira skill neutra, sem materialização nem ativação. Nenhuma skill de terceiros foi implantada por estas entregas.** O `catalog.json` é um inventário de candidatas, não uma coleção de contratos `SKILL.md` aprovados. Para adotar uma skill de verdade, será preciso criar `skills/<nome>/SKILL.md` e `contract.yaml` conforme o [contrato de skill](../docs/contratos/contrato-de-skill.md).

- Fonte neutra conforme [ADR-007](../docs/adr/ADR-007-arquitetura-de-diretorios.md). Nada é materializado em `.claude/` nesta etapa.
- `reported-global` significa instalação **relatada no handoff de outro projeto**, não verificada no toolkit ou no host. O catálogo não desativa nem restringe plugins globais já instalados no Claude Code.
- `candidate` significa apenas pesquisada; `disabled` mantém Superpowers fora das sugestões.
- `approved_for_use: false` e `toolkit_installed: false` são invariantes. O roteador rejeita qualquer entrada que tente alterá-las.
- `license_reported` é informação a confirmar na adoção, não parecer jurídico nem licença automática para redistribuição.

## Roteador offline e consultivo

`python3 scripts/skill_router.py validate` valida o catálogo com a biblioteca padrão do Python 3.11+.

`python3 scripts/skill_router.py suggest --agent ui-ux --tag design_system` retorna até duas sugestões em JSON. Não instala, carrega, importa, executa nem ativa nenhuma skill, agente, hook, MCP ou conexão de rede. Sempre informa `authorization_granted: false` e `skills_loaded: false`.

O coordenador futuro não usa este catálogo automaticamente. Permissões reais do Claude Code, isolamento por worktree e políticas de aprovação continuam necessários. Esta ferramenta **não é sandbox** e não altera nenhum plugin global preexistente.

## Matriz proposta — os 12 domínios futuros (GH-F1.7 ainda não implementada)

| Especialidade | Skills e plugins candidatos | Limite |
|---|---|---|
| `ui-ux` | impeccable, replica-design, frontend-design, web-design-guidelines, anatomy | Sem modificar backend, autenticação ou migrations |
| `frontend` | replica-build, vercel-react-best-practices, vercel-composition-patterns, ponytail | Escrita só com autorização e reserva |
| `backend` | replica-backend, ponytail | Sem credenciais, dados reais ou pagamentos |
| `database` | replica-architect | Modelagem somente; migrations proibidas nesta fase |
| `devops` | replica-deploy | Sugestão apenas; produção/deploy A3 bloqueados |
| `security` | nenhuma skill externa aprovada nesta seleção | Auditoria read-only; Codex independente pendente |
| `qa` | webapp-testing, replica-test, replica-diff | Testar só ambientes autorizados |
| `architecture` | replica-architect, vercel-composition-patterns | Planejar não é autorizar |
| `api` | replica-backend, replica-architect | Contratos; sem escrita não aprovada |
| `performance` | vercel-react-best-practices | Medir primeiro; sem telemetria automática |
| `documentation` | skill-creator, replica-launch | Sem publicação automática |
| `management` | replica-entrepreneur, replica-brand, replica-launch | Pesquisa e plano, sem compras ou deploy |

`motionmaxxing` é candidata para vídeo/mídia, mas Media Lab não foi criada como 13º agente. OpenViking, Google Artemis, Unsloth e CodeXR são **infraestruturas ou referências, não Agent Skills**, e ficam fora do roteamento.


## Revisões pinadas e contratos propostos (GH-F2.1)

A revisão preliminar de seis candidatas de UI/UX, Frontend e QA está registrada em [GH-F2-1-candidates.json](reviews/GH-F2-1-candidates.json), com commits/SHA, licenças observadas, riscos, dependências e **minutas de contrato**. O validador somente leitura `python3 scripts/validate_skill_reviews.py --json` e os testes `python3 -m unittest discover -s tests -p 'test_skill_reviews.py' -v` conferem restrições negativas. Não são `SKILL.md` ou `contract.yaml` instaláveis: são propostas ainda não aprovadas.

Em especial: Impeccable pode obter binário e instalar hooks; Webapp Testing inclui helper `shell=True`; Web Design Guidelines consulta regras remotas mutáveis e não apresentou licença verificada no material revisado. Esses itens **não podem receber ativação automática**. Os níveis de risco no catálogo agora refletem esses achados. Nenhum código de terceiros foi copiado.


## Primeira skill própria (GH-F2.1b, proposta)

[ui-design-review-readonly](ui-design-review-readonly/SKILL.md) é uma definição **original** de revisão UI/UX em modo A0, com [contrato de acesso](ui-design-review-readonly/contract.yaml) e [plano de avaliação](../docs/plans/GH-F2-1b-ui-review-skill.md). Permite somente propor achados com evidências sobre UI já fornecida ou autorizada; não executa Impeccable, Replica, webapp-testing ou qualquer ferramenta de terceiros.

**Fonte neutra não é instalação:** esta pasta não é copiada para `.claude/skills/`, nem habilitada para agentes. O validador `python3 scripts/validate_ui_review_skill.py` verifica estrutura e permissões declaradas; não comprova isolamento real. O contrato usa JSON válido como subconjunto de YAML 1.2 para validação offline pela stdlib. GH-F2.2 (integração aos agentes) continua condicionada à GH-F1.7 e suas verificações.

## Princípios de eficiência e adoção

1. Seleção por especialidade + tag explícitas, sem varrer prompts do usuário.
2. Máximo padrão de duas sugestões; até três mediante argumento específico.
3. Skills de terceiros requerem **avaliação individual de procedência, versão/commit, licença, scripts, hooks, dependências, permissões e prompt injection**, seguida de decisão humana.
4. Referências visuais (CodeXR, Replica) não autorizam copiar código, logos, ativos ou fontes licenciadas.
5. Evitar duplicar Ponytail com Superpowers; Superpowers permanece desativado.
6. Auditoria Codex pendente; SRT do PR #12 não autoriza agente real.

## Testes locais

```bash
python3 scripts/skill_router.py validate
python3 scripts/skill_router.py suggest --agent ui-ux --tag design_system
python3 -m unittest discover -s tests -p 'test_skill_router.py' -v
```

Verificações do catálogo não são auditoria de código de terceiros. Os especialistas continuam documentais/futuros até a GH-F1.7 e respectivos critérios de segurança.
