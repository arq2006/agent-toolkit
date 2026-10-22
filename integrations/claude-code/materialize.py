#!/usr/bin/env python3
"""Materializa agents/<nome>/AGENT.md em .claude/agents/<nome>.md (GH-F1.4, ADR-010).

Só biblioteca padrão + PyYAML. Sem rede, sem shell, sem instalar nada.
Subcomandos:
  agents [--write]      dry-run por padrão (mostra o diff); --write grava só o que
                        `materialize: true` e nunca sobrescreve arquivo diferente.
  git-state             imprime JSON do estado Git (somente leitura) para entregar a agentes sem Bash.
  compare A.json B.json compara estado inicial e final.
"""
import argparse, difflib, hashlib, json, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_FORBIDDEN = {"Bash", "Write", "Edit", "NotebookEdit", "Agent", "WebFetch", "WebSearch"}


def split_front_matter(text):
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


def render(name, spec, src):
    meta, body = split_front_matter(src.read_text())
    lines = [l for l in body.splitlines() if not l.startswith("> Definição documental")]
    body = "\n".join(lines).strip("\n")
    head = {"name": name, "description": " ".join(spec["description"].split()),
            "tools": ", ".join(spec["tools"]), "disallowedTools": ", ".join(spec["disallowedTools"]),
            "model": spec["model"], "effort": spec["effort"]}
    if spec.get("isolation"):
        head["isolation"] = spec["isolation"]
    fm = "\n".join(f"{k}: {v}" for k, v in head.items())
    note = (f"> Gerado de `agents/{name}/AGENT.md` (v{meta['version']}) por "
            "`integrations/claude-code/materialize.py`. Não editar à mão: altere a fonte e regere.")
    extra = ""
    if "Bash" not in spec["tools"]:
        extra = ("\n\n## Execução sem Bash\nEste agente não tem Bash. O invocador (Claude principal ou humano) "
                 "entrega, como dado no pedido, o estado Git inicial (`git-state`: HEAD, branch, status, diff e "
                 "checksums) e, ao final, o estado final para comparação. Se o estado inicial não vier, pare e "
                 "peça-o. Nunca tente executar comandos nem escrever arquivos.")
    return f"---\n{fm}\n---\n{note}\n\n{body}{extra}\n"


def validate(name, spec, meta):
    errs = []
    if meta["name"] != name:
        errs.append("name diverge da fonte")
    if meta["mode"] == "read-only":
        if set(spec["tools"]) & READ_ONLY_FORBIDDEN:
            errs.append(f"agente de leitura com ferramenta proibida: {sorted(set(spec['tools']) & READ_ONLY_FORBIDDEN)}")
        if not READ_ONLY_FORBIDDEN <= set(spec["disallowedTools"]):
            errs.append("disallowedTools não cobre todas as ferramentas de escrita/execução")
    elif spec["materialize"]:
        errs.append("agente com escrita não pode ter materialize: true sem autorização específica")
    return errs


def cmd_agents(write):
    mapping = yaml.safe_load((ROOT / "integrations/claude-code/mapping.yaml").read_text())["agents"]
    rc = 0
    for name, spec in mapping.items():
        src = ROOT / "agents" / name / "AGENT.md"
        meta, _ = split_front_matter(src.read_text())
        errs = validate(name, spec, meta)
        out = ROOT / ".claude/agents" / f"{name}.md"
        new = render(name, spec, src)
        old = out.read_text() if out.exists() else ""
        print(f"== {name}: {'materializar' if spec['materialize'] else 'somente prévia (não gravar)'}")
        for e in errs:
            print(f"ERRO: {e}"); rc = 1
        if old != new:
            sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{out.relative_to(ROOT)}", f"b/{out.relative_to(ROOT)}"))
        else:
            print("sem mudanças")
        if write and spec["materialize"] and not errs:
            if out.exists() and old != new:
                print(f"RECUSADO: {out} existe e difere; analise e aprove antes."); rc = 1
            elif not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True); out.write_text(new); print(f"gravado {out.relative_to(ROOT)}")
    return rc


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=False).stdout


def cmd_git_state():
    diff = git("diff", "HEAD")
    chk = subprocess.run(["sha256sum", "-c", "CHECKSUMS.sha256"], cwd=ROOT / "docs", capture_output=True, text=True)
    print(json.dumps({"head": git("rev-parse", "HEAD").strip(), "branch": git("branch", "--show-current").strip(),
                      "status": git("status", "--porcelain", "--untracked-files=all").splitlines(),
                      "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(), "diff_stat": git("diff", "--stat", "HEAD").splitlines(),
                      "checksums_ok": chk.returncode == 0}, indent=2))


def cmd_compare(a, b):
    A, B = (json.loads(Path(p).read_text()) for p in (a, b))
    diffs = [k for k in A if A[k] != B.get(k)]
    print("estado final idêntico ao inicial" if not diffs else f"DIVERGE em: {diffs}")
    return 1 if diffs else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest="c", required=True)
    s = sp.add_parser("agents"); s.add_argument("--write", action="store_true")
    sp.add_parser("git-state"); c = sp.add_parser("compare"); c.add_argument("a"); c.add_argument("b")
    a = p.parse_args()
    sys.exit({"agents": lambda: cmd_agents(a.write), "git-state": lambda: cmd_git_state() or 0,
              "compare": lambda: cmd_compare(a.a, a.b)}[a.c]())
