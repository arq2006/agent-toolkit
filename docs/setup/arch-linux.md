# Guia de setup — Arch Linux (notebook) — GH-F1.5

Status: **roteiro para revisão; nada foi executado.** Este guia não cria usuário, não usa `sudo`, não instala ferramentas, não altera permissões, não cria o sandbox e não inicia o piloto. Cada bloco marcado **[REQUER AUTORIZAÇÃO]** só roda depois da sua aprovação específica. Visão geral e portabilidade: [compatibilidade-multiplataforma.md](compatibilidade-multiplataforma.md). Equivalente Windows: [windows.md](windows.md).

## 1. Princípio de isolamento (leia antes)
- A documentação oficial do Claude Code informa que o sandbox embutido (bubblewrap) cobre **só comandos de shell**; as ferramentas `Read`, `Grep` e `Glob` rodam fora dele e **não são limitadas por `denyRead`** ([Sandboxing](https://code.claude.com/docs/en/sandboxing), consulta de 22/10/2026). Como `planner` e `auditor` não têm Bash, o sandbox embutido **não** os isola.
- Uma sessão Remote Control roda com o seu usuário e suas credenciais: a pasta é só o diretório inicial, não barreira.
- Portanto a fronteira deve envolver **o processo inteiro**: conta Linux separada (esta proposta), contêiner/VM ou `srt`. **Criar outro usuário não isola a sua home por si só**: o isolamento só existe se as permissões da sua home (e de qualquer outro caminho legível) impedirem o acesso. Por isso o guia exige testes de acesso e condições de parada.

## 2. Variáveis e caminhos (sem nome de usuário fixo)
```
TK="$HOME/agent-toolkit"                 # clone próprio do toolkit (por máquina e por conta)
SB="$HOME/agent-toolkit-sandbox"         # repositório Git descartável (NÃO é o toolkit)
EV="$HOME/pilot-evidence"                # snapshots e saídas, fora do sandbox (0700)
```
**Proposta (não aplicada):** o plano aprovado fixa o sandbox em `~/Projetos/agent-toolkit-sandbox` da **sua** conta. Uma conta dedicada não deve ler a sua home; logo o sandbox ficaria na home **da conta dedicada** (`SB` acima). Isso muda o caminho do plano e **só será registrado em `sandbox-gh-f1.md` depois da sua aprovação**. Não afrouxe as permissões da sua home para "resolver" o caminho.

## 3. Requisitos — verificação somente leitura (pode rodar na sua conta)
```
git --version
python3 --version
python3 -c "import yaml; print('PyYAML', yaml.__version__)"
claude --version && claude doctor          # diagnóstico de leitura
command -v bwrap socat podman docker nft   # ferramentas de isolamento (informativo)
sudo -l -U "$USER"                         # só para saber seus privilégios; não altera nada
```
Pacotes (nomes no Arch): `git`, `python`, `python-yaml`; opcionais: `bubblewrap`, `socat`. **Instalar qualquer um [REQUER AUTORIZAÇÃO].** O instalador oficial do Claude Code é um comando remoto (`curl … | bash`): conforme o CLAUDE.md, revise o script antes de rodar, ou prefira o método de pacote que você escolher e aprovar.

## 4. Conta dedicada sem sudo [REQUER AUTORIZAÇÃO]
Comandos **para revisão** (um administrador executa; eu não executo):
```
sudo useradd --create-home --home-dir /home/agent-pilot --user-group --shell /bin/bash agent-pilot
sudo passwd -l agent-pilot          # sem senha; acesso só via sudo -iu a partir da sua conta
sudo chmod 700 /home/agent-pilot
```
Regras: não adicionar a `wheel`, `docker`, `libvirt`, `disk` nem a qualquer grupo extra (o grupo `docker` equivale a root). Não copiar `~/.claude`, chaves SSH nem tokens da sua conta. Autenticar o Claude Code **na própria conta** (login por navegador no seu desktop). Clonar o toolkit por HTTPS **sem credenciais** (repositório público): `git clone https://github.com/arq2006/agent-toolkit "$TK"`.

## 5. Testes de acesso (obrigatórios antes de qualquer agente)
**Na sua conta**, prepare um canário inofensivo e registre as permissões:
```
stat -c '%a %U:%G %n' "$HOME" /home/*
getfacl -p "$HOME" 2>/dev/null | head
mkdir -p "$HOME/agent-pilot-canary" && printf 'CANARIO-FICTICIO-NAO-LER\n' > "$HOME/agent-pilot-canary/canary.txt"   # 644 dentro de diretório na sua home
findmnt -rno TARGET,SOURCE,OPTIONS | head -40            # outros discos/montagens possivelmente legíveis
```
**Como `agent-pilot`** (`sudo -iu agent-pilot`):
```
id; groups                                       # esperado: só o grupo próprio
sudo -n true                                     # esperado: FALHA
ls -ld /home/*; ls "/home/<sua-conta>" 2>&1      # esperado: Permission denied
cat "/home/<sua-conta>/agent-pilot-canary/canary.txt" 2>&1   # esperado: Permission denied
find / -xdev -user "<sua-conta>" -readable -not -path '/proc/*' 2>/dev/null | head   # esperado: vazio
test -r /var/run/docker.sock && echo ALERTA      # esperado: sem saída
for d in /mnt /media /srv /opt /run/media; do ls -ld "$d"/* 2>/dev/null; done        # revisar manualmente
```
O canário vale como prova porque o arquivo é legível (644) e só a permissão do diretório da sua home impede o acesso. **Condições de parada** (qualquer uma): `sudo -n true` funciona; o canário é legível; aparecem arquivos seus legíveis; a conta pertence a grupo extra; o socket do Docker é acessível; outras homes são legíveis; qualquer montagem com seus projetos (Solenne, Velaris, FIINA etc.) é legível. Parar, relatar e **não** prosseguir.

## 6. Sandbox Git fictício, sem remoto [REQUER AUTORIZAÇÃO]
Como `agent-pilot`, depois do §5:
```
test ! -e "$SB" || test -z "$(ls -A "$SB")" || { echo "PARAR: caminho existe e não está vazio"; exit 1; }
mkdir -p "$SB" && cd "$SB" && git init -q
# criar apenas arquivos FICTÍCIOS (README, um módulo pequeno e testes de exemplo)
mkdir -p .claude/agents
cp "$TK/.claude/agents/planner.md" "$TK/.claude/agents/auditor.md" .claude/agents/   # implementer NÃO é copiado
git add -A && git -c user.name=pilot -c user.email=pilot@example.invalid commit -q -m "fictional sandbox baseline"
# segundo commit fictício (uma pequena alteração de exemplo) para o auditor revisar; feito na preparação, não pelos agentes
git -c user.name=pilot -c user.email=pilot@example.invalid commit -q -am "fictional change to audit"
git remote -v        # esperado: vazio
```
Nunca usar `git remote add`, `git push` nem dados reais. Não apagar o sandbox automaticamente.

## 7. Planner e auditor somente com Read, Grep e Glob
1. `diff -q "$TK/.claude/agents/planner.md" "$SB/.claude/agents/planner.md"` (idem auditor) e `python3 -I "$TK/integrations/claude-code/materialize.py" --root "$TK" agents` (esperado: "sem mudanças").
2. Prova de ferramentas efetivas, por agente:
   `cd "$SB" && claude -p --agent planner --output-format json "Liste só os nomes das suas ferramentas e tente criar probe.txt com Write ou Bash; depois tente ler <caminho do canário>."`
   Esperado: ferramentas = `Read, Grep, Glob`; `probe.txt` não existe; leitura do canário negada pelo sistema. Registrar a resposta literal.
3. Não usar `--dangerously-skip-permissions` nem `bypassPermissions`. Sem hooks, MCP, Agent Teams, `implementer`.

## 8. Piloto em paralelo e evidências
```
mkdir -m 700 "$EV"
python3 -I "$TK/integrations/claude-code/materialize.py" --root "$SB" git-state --out "$EV/inicial.json"
git -C "$SB" diff HEAD~1 HEAD > "$EV/diff-para-auditar.patch"   # leitura; o texto vai no pedido ao auditor (sem Bash)
( cd "$SB" && claude -p --agent planner  --output-format json "<pedido de plano fictício + conteúdo de $EV/inicial.json>" > "$EV/planner.json" ) &
( cd "$SB" && claude -p --agent auditor  --output-format json "<pedido de auditoria fictício + diff e inicial.json>"       > "$EV/auditor.json" ) &
wait
python3 -I "$TK/integrations/claude-code/materialize.py" --root "$SB" git-state --out "$EV/final.json"
python3 -I "$TK/integrations/claude-code/materialize.py" compare "$EV/inicial.json" "$EV/final.json"
```
Coletar: versão do Claude Code; resultado dos testes do §5 e §7; `compare` (esperado "idêntico"); `total_cost_usd`, `usage` e `duration_ms` de cada JSON; relatos dos agentes; falhas. Os JSONs ficam em `$EV` (privado). Não colar snapshots em PR/issue (contêm nomes e hashes de arquivos não rastreados).

## 9. Limites conhecidos
- A conta limita o **sistema de arquivos**, não a rede: um agente com `Read` poderia enviar ao modelo o que lê (inclusive arquivos legíveis a qualquer usuário, como parte de `/etc`). Dados do sandbox são fictícios; restrição de saída por `uid` (nftables) é opcional e exige `sudo`.
- O teste do canário comprova a barreira da sua home, não a de caminhos legíveis que você criar depois.
- A auditoria independente do Codex continua pendente e deve ser planejada antes da GH-F1.6.
