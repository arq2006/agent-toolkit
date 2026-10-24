# GH-F2.1 — Avaliação de skills de UI/UX, Frontend e QA

**Status: revisão preliminar em Draft; adoção, ativação e merge NÃO autorizados por este documento.** Data da coleta: 24/10/2026. Escopo: seis skills do catálogo GH-F2.0, somente documentação, minutas de contratos, atualização do inventário e verificador offline. Respeitar GH-F1.5/F1.6/F1.7 e ADR-007/009. **O PR #12 não certifica STRONG nem autoriza agentes executáveis.**

## Resultado de triagem — não equivale a auditoria completa de dependências

| Candidata | Agente futuro | Fonte | Decisão inicial | Motivo |
|---|---|---|---|---|
| Impeccable | ui-ux (frontend como consumidor) | pbakaus/impeccable | **HOLD** | upstream 4.7.1, instalação histórica relatada 4.6.0 sem verificação local; inicializador/launcher podem baixar binário, plugin pode configurar hooks, comandos escrevem PRODUCT.md/DESIGN.md e código |
| Replica Design | ui-ux | Jakeschincariol/replica-skill | **HOLD** | prompt orienta criar tokens, CSS, componentes; `contrast.py` precisa revisão integral e teste antes de executar; referências não permitem copiar ativos |
| Frontend Design | ui-ux | anthropics/skills | **HOLD** | boa orientação estética, porém sobreposição com Impeccable; manter somente uma orientação visual padrão por tarefa |
| Web Design Guidelines | qa / ui-ux | vercel-labs/agent-skills | **HOLD** | leitura dinâmica de `web-interface-guidelines/main/command.md` e licença **não verificada**; fixar snapshot/revisar licença antes de reutilizar |
| React Best Practices | frontend / performance | vercel-labs/agent-skills | **HOLD** | frontmatter diz MIT; corpus de regras em `rules/` não completamente auditado; medir efeito e evitar refatoração automática |
| Webapp Testing | qa | anthropics/skills | **HOLD — risco alto** | helper `scripts/with_server.py` executa argumentos em `subprocess.Popen(shell=True)`; a instrução upstream para tratar scripts como caixa-preta contradiz nossa revisão prévia obrigatória |

Fontes, SHA do commit, blob da entrypoint, status da licença, fatos observados, ações separadamente autorizáveis, caminhos protegidos, testes propostos e condições de parada estão estruturados em [GH-F2-1-candidates.json](../../skills/reviews/GH-F2-1-candidates.json). Todos os candidatos ficam com `approval=NOT_APPROVED`; os contratos são **`DRAFT_NOT_SKILL`**, não `SKILL.md` distribuído nem `contract.yaml` em produção. Não foi realizada inspeção integral de todos os binários, hooks, scripts auxiliares, regras ou dependências upstream. Nenhum desses recursos foi executado.

### Análise de conflitos e estratégia para poupar contexto

- **Direção visual**: escolher **um** responsável primário por tarefa: Impeccable *ou* Frontend Design. Replica Design complementa somente quando é preciso criar tokens, e sempre após autorização para escrita.
- **Revisão UI e acessibilidade**: Web Design Guidelines só com regras aprovadas e versão congelada; não permitir consulta de `main` no runtime.
- **Frontend React**: React Best Practices apenas em tarefas React/Next.js quando houver hipótese técnica; requer evidência de desempenho antes/depois.
- **QA**: Webapp Testing somente com fixtures descartáveis, porta declarada, política de rede explícita e helper revisado; iniciar serviços não é operação A0.
- **Separação**: UI/UX propõe decisões, Frontend implementa e QA verifica. Worktree e arquivos reservados somente quando houver isolamento de escrita comprovado. Nenhuma skill amplia os limites do agente.

### Licenças e procedência

- Impeccable: Apache-2.0 em `LICENSE`, versão upstream identificada 4.7.1.
- Replica Design: MIT no `LICENSE` do repositório.
- Anthropic Frontend Design e Webapp Testing: Apache-2.0 nos `LICENSE.txt` das respectivas skills.
- React Best Practices: `MIT` declarado no frontmatter; confirmar documentação/termos para cópia substancial.
- Web Design Guidelines: **não verificada**, pois a skill não traz `license` no frontmatter e um `LICENSE` não foi encontrado na raiz. Nenhuma cópia das regras remotas neste PR.

### Contrato de adoção posterior (fora deste PR)

1. Auditar todos os arquivos realmente distribuídos por candidato: `SKILL.md`, `scripts/`, comandos implícitos, hooks, downloads, dependências transitivas e mudanças de ambiente.
2. Confirmar procedência e a licença adequada, pin de commit e checagem de integridade dos artefatos; se necessário, descartar um candidato.
3. Só então propor instância conforme [contrato de skill](../contratos/contrato-de-skill.md): `skills/<nome>/SKILL.md` e `contract.yaml`, preservando a licença, escopo e testes negativos.
4. Solicitar autorização **específica** por ferramenta e ação (instalação, escrita, hooks, rede, execução). O roteador existente segue advisory-only.
5. Testar com entradas sintéticas e projeto descartável; sem promoção para STRONG por conta de canários parciais; sem usar aplicativos/projetos reais até autorização.

### Testes propostos no Arch, sem execução de terceiros

```fish
python3 scripts/skill_router.py validate
python3 scripts/validate_skill_reviews.py --json
python3 -m unittest discover -s tests -p 'test_skill_reviews.py' -v
python3 -m unittest discover -s tests -p 'test_skill_router.py' -v
```

Resultados esperados: `status=VALID`, seis revisões, `permissions_granted=false`, nenhuma importação de skill, nenhum comando externo, testes negativos recusando permissões e licença falsa.

### Escopo Git

Arquivos: `skills/reviews/GH-F2-1-candidates.json`, `scripts/validate_skill_reviews.py`, `tests/test_skill_reviews.py`, `skills/catalog.json`, `skills/README.md`, `policies/inventario-ferramentas-integracoes.md` e este plano. Não alterar `.claude/`, `AGENTS.md`, `CLAUDE.md`, banco, produção, Solenne ou documentos imutáveis. Auditoria Codex independente ainda pendente; não declarar executada. Abrir **Draft PR**, não habilitar auto-merge.

**Critérios de aceite do Draft**: revisão e SHA reproduzíveis, provas negativas, policy/inventário coerentes, Git diff limitado ao escopo, revisão humana; merge somente com autorização específica posterior.
