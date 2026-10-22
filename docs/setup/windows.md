# Guia de setup — Windows 10/11 (PC principal, uso futuro) — GH-F1.5

Status: **somente documentação; nada foi instalado, configurado ou executado no Windows.** Mesmos contratos, agentes, `mapping.yaml` e critérios de teste do [guia Arch Linux](arch-linux.md); aqui só mudam o ambiente e os comandos. Portabilidade do código e sincronização: [compatibilidade-multiplataforma.md](compatibilidade-multiplataforma.md). Itens sobre recursos do Windows/WSL/Hyper-V vêm de conhecimento geral e **devem ser conferidos na documentação oficial da Microsoft antes de qualquer execução**; o que cita o Claude Code vem da documentação oficial consultada em 22/10/2026 (setup, sandboxing, sandbox-environments).

> **Portabilidade do gerador:** o uso nativo de `materialize.py` no Windows exige uma etapa separada de implementação e testes (ver [compatibilidade](compatibilidade-multiplataforma.md) §2). A preparação do Windows continua só documentada; nada foi executado.

## 1. O que a documentação do Claude Code diz (fatos que orientam a escolha)
- Windows suportado: 10 versão 1809+ ou Server 2019+; shells PowerShell/CMD; Git for Windows é recomendado para a ferramenta Bash (sem ele, usa PowerShell).
- **Windows nativo não tem o sandbox de Bash**; ele existe em macOS, Linux e **WSL2** (não no WSL1).
- Mesmo onde existe, o sandbox cobre só comandos de shell; `Read`/`Grep`/`Glob` ficam fora. Para limitar o processo inteiro a documentação indica contêiner, VM ou `srt`; para repositório não confiável, **VM dedicada**.
- Logo, nenhuma opção abaixo é segura "só porque roda no Windows": o isolamento tem de vir de **conta, WSL configurado, VM ou Windows Sandbox**, com testes de acesso.

## 2. Comparação das opções
| Opção | Home | Pro/Ent/Edu | Isolamento real | Prático | Observações |
|---|---|---|---|---|---|
| Claude Code **nativo**, conta Windows padrão + NTFS | sim | sim | só o que as ACLs impõem; sem sandbox de Bash | alto | exige provar com `icacls` e testes; unidades de dados podem conceder leitura a `Users`/`Authenticated Users` |
| **WSL2** (sem configurar) | sim | sim | **fraco**: por padrão monta as unidades do Windows em `/mnt/<letra>` com as permissões do seu usuário e tem interoperabilidade | alto | não presumir isolamento |
| **WSL2 dedicado e endurecido** (distro própria, `automount` e `interop` desligados, usuário sem sudo) | sim | sim | médio; depende de `/etc/wsl.conf`; o host Windows continua alcançável pela rede | médio | permite o sandbox de Bash e reutiliza o roteiro Linux |
| **Windows Sandbox** | **não** | sim | alto e descartável; pasta mapeada só leitura; rede desativável | baixo (reinstala e reloga a cada uso) | cada sessão perde estado; credenciais ficam só enquanto a janela existir |
| **VM** (Hyper-V no Pro; VirtualBox/VMware nas duas edições) com convidado **Linux** | sim (VirtualBox/VMware) | sim | **alto**; kernel próprio, snapshots | médio | roda o roteiro do Arch dentro do convidado, com os mesmos critérios |

**Recomendação:** (1) **VM com convidado Linux** e usuário sem sudo, repetindo o [roteiro do Arch](arch-linux.md) (mesmos testes e critérios; mais forte que conta ou WSL). (2) Se VM for inviável, **conta Windows padrão dedicada com ACLs NTFS provadas**. (3) WSL2 só endurecido e com os testes do §5. Windows Sandbox serve para execuções curtas e descartáveis no Pro. Em Home, use a VM de terceiros ou a conta padrão.

## 3. Variáveis e caminhos independentes de usuário e de letra de unidade (PowerShell)
```powershell
$TK = Join-Path $env:USERPROFILE 'agent-toolkit'            # clone próprio do toolkit
$SB = Join-Path $env:USERPROFILE 'agent-toolkit-sandbox'    # repositório Git descartável (NÃO é o toolkit)
$EV = Join-Path $env:LOCALAPPDATA 'agent-pilot-evidence'    # snapshots, fora do sandbox
```
Não escrever `C:\Users\<nome>` nem letras de unidade em guias, scripts ou prompts; enumerar unidades com `Get-PSDrive -PSProvider FileSystem`. Usar `/` ou `Join-Path` nas ferramentas do toolkit.

## 4. Conta padrão com NTFS [REQUER AUTORIZAÇÃO — nada foi criado]
Comandos para revisão, em PowerShell de administrador, executados por você:
```powershell
$pw = Read-Host -AsSecureString 'Senha da conta de piloto'
New-LocalUser -Name 'agent-pilot' -Password $pw
Get-LocalGroupMember -Group 'Administrators'                 # esperado: agent-pilot AUSENTE
```
Usar a conta: `runas /user:agent-pilot powershell` (funciona em Home e Pro). Não adicionar a Administrators, "Hyper-V Administrators" nem "docker-users". Não copiar `%USERPROFILE%\.claude`, tokens ou o Credential Manager da sua conta; autenticar o Claude Code na própria conta.

## 5. Testes de acesso (obrigatórios; equivalentes ao §5 do guia Arch)
Na sua conta, crie o canário e registre as ACLs:
```powershell
$can = Join-Path $env:USERPROFILE 'agent-pilot-canary'
New-Item -ItemType Directory $can | Out-Null; 'CANARIO-FICTICIO-NAO-LER' | Set-Content (Join-Path $can 'canary.txt')
icacls $env:USERPROFILE
Get-PSDrive -PSProvider FileSystem | ForEach-Object { icacls $_.Root }     # raízes de todas as unidades
```
Como `agent-pilot`:
```powershell
whoami /groups                                              # esperado: sem Administrators
Get-ChildItem "$env:SystemDrive\Users" -Directory | ForEach-Object {       # perfis de outras contas
  $ok = $true; try { Get-ChildItem $_.FullName -ErrorAction Stop | Out-Null } catch { $ok = $false }
  "{0}: legível={1}" -f $_.Name, $ok }                      # esperado: só o perfil próprio e Public
Get-Content '<caminho do canário>' -ErrorAction SilentlyContinue   # esperado: acesso negado
Get-PSDrive -PSProvider FileSystem | ForEach-Object { try { Get-ChildItem $_.Root -ErrorAction Stop | Select-Object -First 5 | Out-Null; "$($_.Root) legível" } catch { "$($_.Root) negado" } }  # revisar cada unidade
```
**Condições de parada:** a conta está em Administrators; o canário é legível; algum perfil de outra conta é legível; uma unidade de dados com seus projetos é legível a `Users`/`Authenticated Users` (corrigir as ACLs é decisão sua, **nunca minha**); WSL/VM exposta com compartilhamento do seu perfil.

## 6. WSL2 endurecido (se escolhido) [REQUER AUTORIZAÇÃO]
Não presumir isolamento. Para revisão, dentro de uma distro **dedicada** (`wsl --import`, sem reutilizar a sua distro) e com usuário padrão **sem sudo**, em `/etc/wsl.conf`:
```
[automount]
enabled = false
[interop]
enabled = false
appendWindowsPath = false
[user]
default = agent-pilot
```
Depois de `wsl --shutdown`, provar: `ls /mnt` vazio; `mount -t drvfs C: /mnt/c` falha para o usuário sem sudo; `cmd.exe` indisponível; `$HOME` fora de `/mnt`. Limites: a distro roda sob o **seu** usuário Windows, o host continua alcançável pela rede e, do Windows, o conteúdo da distro aparece em `\\wsl.localhost\`. Qualquer falha dos testes encerra o uso desta opção.

## 7. Equivalentes PowerShell dos procedimentos Linux
| Linux | Windows (PowerShell) |
|---|---|
| `python3 -I script.py` | `py -3 -I script.py` (ou `python -I`; confirme com `py -0p`) |
| `sha256sum -c docs/CHECKSUMS.sha256` | hoje só no Git Bash; ver [compatibilidade](compatibilidade-multiplataforma.md) (proposta de verificação em Python). Equivalente manual: `(Get-FileHash <arquivo> -Algorithm SHA256).Hash.ToLower()` |
| `umask 077; mktemp -d` | `New-Item -ItemType Directory (Join-Path $env:LOCALAPPDATA 'agent-pilot-evidence')` e, **em seguida**, `icacls` para remover herança e deixar só o usuário atual (`icacls $EV /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F"`) |
| `chmod 700` / `stat -c %a` | `icacls` / `Get-Acl` |
| `ls -ld`, `getfacl` | `Get-Acl`, `icacls` |
| `claude -p … > arquivo` | `claude -p … \| Set-Content -Encoding utf8` (confirmar a codificação da saída) |
| execução em paralelo (`&`/`wait`) | `Start-Job` ou `Start-Process` para cada agente e `Wait-Job` |
| `sudo -n true` | `net session` (falha sem elevação) |

## 8. Piloto, evidências e critérios
Mesmos testes, comandos conceituais e critérios do [§7–§8 do guia Arch](arch-linux.md), com `$TK`, `$SB` e `$EV` acima: ferramentas efetivas só `Read, Grep, Glob`; tentativa de escrita e leitura do canário falham; snapshots Git inicial e final idênticos; execução paralela de planner e auditor; consumo (`total_cost_usd`, `usage`, `duration_ms`) e falhas registrados. **Pendência técnica:** `git-state --out` no Windows exige as adaptações propostas na [auditoria de portabilidade](compatibilidade-multiplataforma.md); sem elas o comando falha de forma segura (erro) e não produz snapshot.

## 9. Fora do escopo desta rodada
Instalar Claude Code, Git, Python, WSL, Hyper-V ou VM; criar contas; alterar ACLs ou o registro; qualquer teste no Windows. O Codex continua pendente.
