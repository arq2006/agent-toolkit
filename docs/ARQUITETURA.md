# Arquitetura de diretórios do Agent Toolkit

Status: **desenho** (F0.2). Nenhum dos diretórios abaixo é criado agora; cada um nasce na fase indicada, junto com conteúdo real e testes. Decisão registrada na [ADR-007](adr/ADR-007-arquitetura-de-diretorios.md).

## Princípios
1. **Fonte neutra, materialização por ferramenta.** Definições de agentes e skills vivem em diretórios neutros; cada ferramenta (Claude Code, Codex, Hermes, outras) recebe uma camada fina de adaptação.
2. **Claude Code primeiro.** O layout deve funcionar com `.claude/agents/`, `.claude/skills/` e `CLAUDE.md`; a forma de materialização (cópia, symlink ou plugin) é decidida na GH-F1, após conferir a documentação oficial atual.
3. **Compatível com Codex e outros.** `AGENTS.md` é o ponto de entrada comum; o que for específico de uma ferramenta fica em `integrations/<ferramenta>/`.
4. **Nada específico de cliente.** Adaptadores por projeto vivem nos projetos; aqui só o modelo (`template`).
5. **Sem segredos nem dados pessoais** em nenhum diretório (repositório público).

## Árvore alvo

```text
agent-toolkit/
├── README.md · CLAUDE.md · AGENTS.md
├── docs/                      # existente
│   ├── ARQUITETURA.md · ROADMAP_IMPLEMENTACAO.md · DECISOES.md · ...
│   ├── adr/                   # decisões detalhadas
│   ├── references/ · security/  # importados na F0.1; imutáveis (ver CHECKSUMS.sha256)
│   └── compliance/            # checklist jurídico, mapa de dados, relatório (F0.2)
├── policies/                  # GH-F0: inventário de ferramentas e matriz de riscos/permissões/aprovações (existentes); segurança de dados (futuro)
├── agents/                    # GH-F1.2 (existente): definições documentais neutras (planner, implementer, auditor)
├── skills/                    # GH-F2: skills no padrão Agent Skills (SKILL.md + apoio)
├── workflows/                 # GH-F1/F2: fluxos (feature, bugfix, audit, media), contrato de tarefa
├── integrations/              # GH-F3+: tudo que toca ferramenta ou provedor externo
│   ├── claude-code/           #   materialização para .claude/ (regras e scripts de sincronização com dry-run)
│   ├── codex/ · hermes/       #   camadas de adaptação por agente (somente quando houver necessidade real)
│   ├── mcp/                   #   conectores MCP próprios (PDF: connectors/mcp)
│   └── adapters/template/     #   modelo de adaptador por projeto (PDF: adapters/)
├── experiments/               # GH-F4/F5: hermes, freellmapi, elevenlabs; isolados, sem produção
├── src/                       # somente se/quando houver tecnologia escolhida (GH-F3)
├── tests/                     # skills, security, contracts
├── examples/                  # exemplos com dados fictícios
├── scripts/                   # utilitários revisados; nenhum executável sem revisão
├── .claude/                   # camada de materialização para Claude Code (GH-F1)
└── .github/workflows/         # CI, somente com aprovação
```

## Mapa de reconciliação (PDF seção 13 × README × decisão)

| PDF (`ai-agent-toolkit`) | README anterior | Decisão |
|---|---|---|
| `policies/` | — | `policies/` |
| `agents/` | `.claude/agents/` | fonte em `agents/`; `.claude/agents/` é materialização |
| `skills/` | `.claude/skills/` | fonte em `skills/`; `.claude/skills/` é materialização |
| `workflows/` | — | `workflows/` |
| `connectors/mcp/` | `integrations/` | `integrations/mcp/` |
| `adapters/{solenne,fiina,velaris,template}/` | `integrations/` | apenas `integrations/adapters/template/`; adaptadores reais ficam nos projetos |
| `experiments/` | — | `experiments/` |
| `tests/`, `scripts/`, `.github/workflows/` | `tests/`, `src/` | mantidos |
| `docs/architecture.md`, `docs/roadmap.md` | `docs/` | `docs/ARQUITETURA.md`, `docs/ROADMAP_IMPLEMENTACAO.md` |
| — | `examples/` | mantido |

## Contratos (a definir antes de criar agentes e skills)
- **Agente:** nome, responsabilidade, ferramentas permitidas, escopo de arquivos, modo (leitura ou escrita), modelo sugerido, critérios de aceite, formato de relato.
- **Skill:** `SKILL.md` com nome, descrição de quando usar, entradas, saídas, permissões, testes e versão semântica.
- **Tarefa:** dono, branch, worktree, arquivos reservados, critérios de aceite, evidências.
Os formatos finais são definidos na GH-F1 e registrados em ADR.

## Como outras ferramentas consomem o toolkit
- **Claude Code:** `CLAUDE.md` + `.claude/` gerado a partir de `agents/` e `skills/` (dry-run antes de gravar; nunca sobrescrever `CLAUDE.md`/`AGENTS.md` de outros projetos).
- **Codex:** `AGENTS.md` e, se necessário, `integrations/codex/`.
- **Hermes e outros:** apenas via `integrations/<ferramenta>/` e `experiments/`, em ambiente isolado, após aprovação da GH-F4.
- **Instalação em outros projetos:** plugin versionado, symlink controlado ou sincronização com dry-run (PDF seção 13); sem cópia de credenciais.
