#!/usr/bin/env python3
"""Materializa agents/<nome>/AGENT.md em .claude/agents/<nome>.md (GH-F1.4, ADR-010).

Só biblioteca padrão + PyYAML. Sem rede, sem shell, sem instalar nada.
Subcomandos (opção global --root só para testes em diretório descartável):
  agents [--write]      dry-run por padrão (mostra o diff); --write grava só o que tem
                        `materialize: true`, depois de validar TODOS os agentes, sem sobrescrever.
  git-state             imprime JSON do estado Git (somente leitura); erro se algum comando Git falhar.
  compare A.json B.json compara estado inicial e final.

Validações implementadas (ver docs/materializacao-claude-code.md): nome, mapeamento sem chaves
desconhecidas, ferramentas conhecidas, planner/auditor só com Read/Grep/Glob, A0 e file_scope none no
contrato de origem, modelo/esforço iguais à política, caminhos protegidos declarados, destino seguro.
Pendente de esquema formal: stop_conditions x matriz, mapa T-xx -> ferramenta, regras `deny` de caminhos.
"""
import argparse, difflib, hashlib, json, os, re, subprocess, sys
from pathlib import Path

import yaml

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
READ_ONLY_TOOLS = {"Read", "Grep", "Glob"}
READ_ONLY_FORBIDDEN = {"Bash", "Write", "Edit", "NotebookEdit", "Agent", "WebFetch", "WebSearch"}
KNOWN_TOOLS = READ_ONLY_TOOLS | READ_ONLY_FORBIDDEN
SPEC_KEYS = {"description", "tools", "disallowedTools", "model", "effort", "isolation", "materialize"}
REQUIRED_SPEC_KEYS = SPEC_KEYS - {"isolation"}
PROTECTED = {"docs/references/", "docs/security/", "docs/CHECKSUMS.sha256"}
MODES = {"read-only", "write-scoped"}


def split_front_matter(text):
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


def inside(child, parent):
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def source_path(root, name):
    p = root / "agents" / name / "AGENT.md"
    return p if p.is_file() and not p.is_symlink() and inside(p, root / "agents") else None


def validate(root, name, spec, meta):
    errs = []
    if not isinstance(name, str) or not NAME_RE.match(name):
        return [f"nome de agente inválido: {name!r}"]
    if not isinstance(spec, dict):
        return ["entrada do mapeamento não é um objeto"]
    if set(spec) - SPEC_KEYS:
        errs.append(f"chaves desconhecidas no mapeamento: {sorted(set(spec) - SPEC_KEYS)}")
    if REQUIRED_SPEC_KEYS - set(spec):
        return errs + [f"chaves ausentes no mapeamento: {sorted(REQUIRED_SPEC_KEYS - set(spec))}"]
    for k in ("tools", "disallowedTools"):
        if not (isinstance(spec[k], list) and all(isinstance(t, str) for t in spec[k])):
            return errs + [f"{k} deve ser lista de textos"]
        if set(spec[k]) - KNOWN_TOOLS:
            errs.append(f"{k} com ferramenta desconhecida: {sorted(set(spec[k]) - KNOWN_TOOLS)}")
    if not (isinstance(spec["description"], str) and 0 < len(spec["description"].strip()) <= 1024):
        errs.append("description deve ser texto de 1 a 1024 caracteres")
    if not isinstance(spec["materialize"], bool):
        errs.append("materialize deve ser booleano")
    if spec.get("isolation") not in (None, "worktree"):
        errs.append("isolation só aceita worktree")
    if not isinstance(meta, dict) or meta.get("name") != name:
        return errs + ["name do contrato diverge do nome do agente"]
    if meta.get("mode") not in MODES:
        errs.append(f"mode desconhecido no contrato: {meta.get('mode')!r}")
    pol = meta.get("model_policy") or {}
    if spec.get("model") != pol.get("default") or spec.get("effort") != pol.get("effort"):
        errs.append("model/effort diferem da model_policy do contrato")
    if not PROTECTED <= set(meta.get("protected_paths") or []):
        errs.append("contrato não declara todos os caminhos protegidos")
    if meta.get("mode") == "read-only":
        if set(spec["tools"]) != READ_ONLY_TOOLS:
            errs.append(f"agente de leitura deve ter exatamente {sorted(READ_ONLY_TOOLS)}; tem {sorted(spec['tools'])}")
        if not READ_ONLY_FORBIDDEN <= set(spec["disallowedTools"]):
            errs.append("disallowedTools não cobre todas as ferramentas de escrita/execução")
        if spec.get("isolation"):
            errs.append("agente de leitura não usa isolation")
        if meta.get("file_scope") != "none":
            errs.append("agente de leitura exige file_scope none no contrato")
        if "write_files" not in (meta.get("forbidden_actions") or []):
            errs.append("contrato de leitura deve proibir write_files")
        bad = [a for a in meta.get("allowed_actions") or [] if not (isinstance(a, dict) and a.get("level") == "A0")]
        if bad or not meta.get("allowed_actions"):
            errs.append("contrato de leitura só pode ter ações de nível A0")
    elif spec["materialize"] is True:
        errs.append("agente com escrita não pode ter materialize: true sem autorização específica")
    return errs


def render(name, spec, meta, body):
    lines = [l for l in body.splitlines() if not l.startswith("> Definição documental")]
    body = "\n".join(lines).strip("\n")
    head = {"name": name, "description": " ".join(spec["description"].split()),
            "tools": ", ".join(spec["tools"]), "disallowedTools": ", ".join(spec["disallowedTools"]),
            "model": spec["model"], "effort": spec["effort"]}
    if spec.get("isolation"):
        head["isolation"] = spec["isolation"]
    fm = yaml.safe_dump(head, sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False)
    if yaml.safe_load(fm) != head:
        raise ValueError(f"YAML gerado não reproduz os campos de {name}")
    note = (f"> Gerado de `agents/{name}/AGENT.md` (v{meta['version']}) por "
            "`integrations/claude-code/materialize.py`. Não editar à mão: altere a fonte e regere.")
    extra = ""
    if "Bash" not in spec["tools"]:
        extra = ("\n\n## Execução sem Bash\nEste agente não tem Bash. O invocador (Claude principal ou humano) "
                 "entrega, como dado no pedido, o estado Git inicial (`git-state`: HEAD, branch, status, hashes de diff "
                 "e de arquivos não rastreados, checksums) e, ao final, o estado final para comparação. Se o estado "
                 "inicial não vier, pare e peça-o. Nunca tente executar comandos nem escrever arquivos.")
    return f"---\n{fm}---\n{note}\n\n{body}{extra}\n"


def dest_errors(root, name):
    """Destino só em <root>/.claude/agents/<name>.md, sem symlinks no caminho."""
    errs, p = [], root
    for part in (".claude", "agents"):
        p = p / part
        if p.is_symlink():
            errs.append(f"{p.relative_to(root)} é link simbólico")
        elif p.exists() and not p.is_dir():
            errs.append(f"{p.relative_to(root)} não é diretório")
    out = p / f"{name}.md"
    if out.is_symlink():
        errs.append(f"{out.relative_to(root)} é link simbólico")
    if not errs and not inside(out.parent, root / ".claude" / "agents") or not inside(out.parent, root):
        errs.append("destino fora de .claude/agents/")
    return out, errs


def plan(root):
    mpath = root / "integrations/claude-code/mapping.yaml"
    mapping = (yaml.safe_load(mpath.read_text()) or {}).get("agents")
    if not isinstance(mapping, dict) or not mapping:
        return [], ["mapping.yaml sem agentes"]
    items, global_errs = [], []
    for name, spec in mapping.items():
        errs, new, out, old = [], "", None, ""
        src = source_path(root, name) if isinstance(name, str) and NAME_RE.match(name) else None
        if src is None:
            errs.append(f"fonte agents/{name}/AGENT.md ausente, inválida ou fora de agents/")
            errs += validate(root, name, spec, None) if not (isinstance(name, str) and NAME_RE.match(name)) else []
        else:
            meta, body = split_front_matter(src.read_text())
            errs += validate(root, name, spec, meta)
            out, derrs = dest_errors(root, name)
            errs += derrs
            if not errs:
                new = render(name, spec, meta, body)
                old = out.read_text() if out.exists() else ""
                if spec["materialize"] and out.exists() and old != new:
                    errs.append(f"{out.relative_to(root)} existe e difere; analise e aprove antes")
        items.append({"name": name, "spec": spec, "out": out, "old": old, "new": new, "errs": errs})
    return items, global_errs


def cmd_agents(root, write):
    items, gerrs = plan(root)
    rc = 1 if gerrs else 0
    for e in gerrs:
        print(f"ERRO: {e}")
    for it in items:
        mat = isinstance(it["spec"], dict) and it["spec"].get("materialize") is True
        print(f"== {it['name']}: {'materializar' if mat else 'somente prévia (não gravar)'}")
        for e in it["errs"]:
            print(f"ERRO: {e}"); rc = 1
        if it["new"] and it["old"] != it["new"]:
            rel = it["out"].relative_to(root)
            sys.stdout.writelines(difflib.unified_diff(it["old"].splitlines(True), it["new"].splitlines(True), f"a/{rel}", f"b/{rel}"))
        elif it["new"]:
            print("sem mudanças")
    if write and rc == 0:
        for it in items:  # só chega aqui com TODOS os agentes válidos
            if it["spec"]["materialize"] and not it["old"]:
                it["out"].parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(it["out"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
                with os.fdopen(fd, "w") as f:
                    f.write(it["new"])
                print(f"gravado {it['out'].relative_to(root)}")
    elif write:
        print("NADA gravado: há erros (sem materialização parcial).")
    return rc


class GitError(RuntimeError):
    pass


def run(root, cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd or root, capture_output=True, check=False)
    if r.returncode != 0:
        raise GitError(f"falha em {' '.join(cmd[:4])}...: código {r.returncode}")
    return r.stdout


def file_sha256(path):
    if path.is_symlink():
        return "symlink:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state(root):
    g = lambda *a: run(root, ["git", "-C", str(root), *a])
    untracked = {}
    for rel in g("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"):
        if rel:
            untracked[rel] = file_sha256(root / rel)
    diff = g("diff", "HEAD")
    chk = None
    if (root / "docs/CHECKSUMS.sha256").exists():
        chk = subprocess.run(["sha256sum", "-c", "CHECKSUMS.sha256"], cwd=root / "docs", capture_output=True).returncode == 0
    return {"head": g("rev-parse", "HEAD").decode().strip(), "branch": g("branch", "--show-current").decode().strip(),
            "status": g("status", "--porcelain", "--untracked-files=all").decode().splitlines(),
            "diff_sha256": hashlib.sha256(diff).hexdigest(), "diff_stat": g("diff", "--stat", "HEAD").decode().splitlines(),
            "untracked_sha256": untracked, "checksums_ok": chk}


def cmd_compare(a, b):
    A, B = (json.loads(Path(p).read_text()) for p in (a, b))
    diffs = sorted(k for k in set(A) | set(B) if A.get(k) != B.get(k))
    print("estado final idêntico ao inicial" if not diffs else f"DIVERGE em: {diffs}")
    return 1 if diffs else 0


def main(argv=None):
    p = argparse.ArgumentParser(); p.add_argument("--root", default=str(DEFAULT_ROOT))
    sp = p.add_subparsers(dest="c", required=True)
    s = sp.add_parser("agents"); s.add_argument("--write", action="store_true")
    sp.add_parser("git-state"); c = sp.add_parser("compare"); c.add_argument("a"); c.add_argument("b")
    a = p.parse_args(argv); root = Path(a.root).resolve()
    try:
        if a.c == "agents":
            return cmd_agents(root, a.write)
        if a.c == "git-state":
            print(json.dumps(git_state(root), indent=2)); return 0
        return cmd_compare(a.a, a.b)
    except (GitError, OSError, ValueError, yaml.YAMLError) as e:
        print(f"ERRO: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
