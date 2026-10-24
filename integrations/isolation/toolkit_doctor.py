#!/usr/bin/env python3
"""Toolkit doctor (GH-F1.8, ADR-011, PR3). Diagnóstico do isolamento; NÃO autoriza executar agentes.

Uso (sem instalação global):
    python3 integrations/isolation/toolkit_doctor.py --config /caminho/toolkit.toml [--json]

Os canários rodam só em árvore sintética descartável (diretório temporário 0700, marcadores
fictícios); nenhum arquivo real é lido ou escrito. A pasta autorizada da configuração é apenas
validada. Nesta etapa STRONG é indisponível e operações com arquivos ficam sempre BLOCKED:
mesmo com todos os canários PASS, o resultado descreve o SRT, não libera agentes.

Códigos de saída: 0 = todos os canários obrigatórios passaram (não autoriza nada);
2 = algum canário falhou ou não pôde ser executado; 3 = configuração inválida ou plataforma
não suportada.
"""
import argparse
import dataclasses
import json
import os
import sys
import tempfile

import isolation_config
import pathguard
import srt_launcher as L

PASS, FAIL, NOT_TESTED, INFO = "PASS", "FAIL", "NOT_TESTED", "INFO"

LIMITATIONS = (
    "STRONG indisponível no PR3: critérios (a)-(f) da ADR-011 pendentes (revisão humana e auditoria independente do Codex).",
    "Hardlinks preexistentes podem permitir leitura de arquivo fora da pasta autorizada; o pathguard só protege o executor, não Read/Edit nativos.",
    "TOCTOU, bind mounts e troca concorrente de diretórios não são cobertos por nenhum canário.",
    "Canários rodam em fixture sintético em /tmp (ou TMPDIR do doctor), não na pasta real do usuário.",
    "Claude autenticado dentro da fronteira, Ollama, LM Studio, MCP e Agent Teams não foram testados.",
    "WSL2 e macOS sem validação; Windows nativo fora do escopo.",
    "Sockets Unix, resolução DNS e allowlist de rede não são exercitados (allowlist é recusada).",
    "A versão exata do srt (0.0.81) é exigida; outras não são presumidas compatíveis.",
    "auth.mode = claude-ai-outside-boundary descreve um coordenador autenticado FORA da fronteira: não é isolamento integral.",
)


class Report:
    def __init__(self):
        self.checks = []

    def add(self, cid, title, status, reason="", mandatory=True):
        self.checks.append({"id": cid, "title": title, "status": status, "reason": reason,
                            "mandatory": mandatory})

    def not_tested(self, ids_titles, reason):
        for cid, title in ids_titles:
            self.add(cid, title, NOT_TESTED, reason)


CANARY_CHECKS = (
    ("canary_run", "Suíte de canários executou dentro do srt"),
    ("auth_read_write", "Leitura e escrita permitidas na pasta autorizada sintética"),
    ("outside_read_blocked", "Leitura de decoy externo bloqueada"),
    ("outside_write_blocked", "Escrita/criação fora da pasta autorizada bloqueada"),
    ("home_decoy_blocked", "Decoy de home fictícia bloqueado"),
    ("policy_file_hidden", "Arquivo de política não legível dentro do sandbox"),
    ("subprocess_restricted", "Subprocesso herda as restrições"),
    ("dotdot_blocked", "Caminho com '..' para fora bloqueado"),
    ("proc_blocked", "Leitura de /proc do processo do host bloqueada"),
    ("tcp_loopback_blocked", "TCP para loopback do host bloqueado"),
    ("tcp_external_blocked", "TCP para interface não loopback do host bloqueado"),
    ("env_not_inherited", "Ambiente do host (segredo fictício) não herdado"),
)


def _slurp(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _check_canaries(rep, fx, res, listeners, sentinel_env_ok):
    r = res.results

    def g(name):
        return r.get(name, {})

    # Os controles positivos validam que o canário rodou de verdade: sem eles, "bloqueado" não conta.
    ar, aw, ac = g("auth_read"), g("auth_write"), g("auth_child_read")
    wrote = _slurp(fx.auth_write) == b"probe-write"
    ctl_ok = ar.get("ok") and fx.auth_marker in ar.get("data", "") and aw.get("ok") and wrote
    if ctl_ok:
        rep.add("auth_read_write", dict(CANARY_CHECKS)["auth_read_write"], PASS)
    else:
        rep.add("auth_read_write", dict(CANARY_CHECKS)["auth_read_write"], FAIL,
                f"controle positivo falhou (leitura={ar.get('err', ar.get('ok'))}, escrita={aw.get('err', aw.get('ok'))}, "
                f"gravou={wrote}); possível falta de leitura mínima do runtime. stderr: {res.stderr_tail[-300:]!r}")
    if not ctl_ok:
        rep.not_tested([c for c in CANARY_CHECKS if c[0] not in ("canary_run", "auth_read_write")],
                       "controle positivo falhou: um bloqueio observado não prova a política")
        return

    def leaked(name, marker):
        v = g(name)
        return v.get("ok") and marker in v.get("data", "")

    t = dict(CANARY_CHECKS)
    rep.add("outside_read_blocked", t["outside_read_blocked"],
            FAIL if leaked("ext_read", fx.secret_marker) else (PASS if "ext_read" in r else NOT_TESTED),
            "decoy externo lido" if leaked("ext_read", fx.secret_marker) else "")
    tgt = _slurp(fx.external_target) == ("ORIGINAL-" + fx.nonce).encode()
    created = os.path.exists(fx.external_new)
    w_leak = g("ext_write_existing").get("ok") or g("ext_create").get("ok") or not tgt or created
    rep.add("outside_write_blocked", t["outside_write_blocked"], FAIL if w_leak else PASS,
            "escrita fora da pasta autorizada ocorreu" if w_leak else "")
    rep.add("home_decoy_blocked", t["home_decoy_blocked"],
            FAIL if leaked("home_decoy_read", "FAKE-KEY-") else PASS)
    rep.add("policy_file_hidden", t["policy_file_hidden"], FAIL if g("settings_read").get("ok") else PASS)
    child_leak = leaked("child_ext_read", fx.secret_marker) or g("child_ext_write").get("ok")
    child_ctl = ac.get("ok") and fx.auth_marker in ac.get("data", "")
    if not child_ctl:
        rep.add("subprocess_restricted", t["subprocess_restricted"], NOT_TESTED,
                "controle positivo do subprocesso falhou")
    else:
        rep.add("subprocess_restricted", t["subprocess_restricted"], FAIL if child_leak else PASS,
                "subprocesso alcançou arquivo externo" if child_leak else "")
    rep.add("dotdot_blocked", t["dotdot_blocked"], FAIL if leaked("dotdot_read", fx.secret_marker) else PASS)
    rep.add("proc_blocked", t["proc_blocked"],
            FAIL if g("proc_host").get("ok") else (PASS if "proc_host" in r else NOT_TESTED),
            "ambiente/cmdline de processo do host legível" if g("proc_host").get("ok") else "")
    for label, cid in (("loopback", "tcp_loopback_blocked"), ("external", "tcp_external_blocked")):
        op = "tcp_" + label
        if label not in listeners.socks or op not in r:
            rep.add(cid, t[cid], NOT_TESTED, "sem ouvinte/interface para este teste neste host")
        elif not listeners.control_ok.get(label):
            rep.add(cid, t[cid], NOT_TESTED, "controle falhou: o próprio host não alcançou o ouvinte")
        else:
            bad = r[op].get("ok") or listeners.hits.get(label, 0) > 0
            rep.add(cid, t[cid], FAIL if bad else PASS, "conexão chegou ao host" if bad else "")
    e = g("env")
    if not e.get("ok"):
        rep.add("env_not_inherited", t["env_not_inherited"], NOT_TESTED, "sem relatório de ambiente")
    else:
        extra = sorted(set(e["keys"]) - set(L.ENV_ALLOWED))
        if not sentinel_env_ok:
            rep.add("env_not_inherited", t["env_not_inherited"], NOT_TESTED, "controle: segredo fictício ausente no host")
        else:
            bad = e.get("sentinel_visible")
            rep.add("env_not_inherited", t["env_not_inherited"], FAIL if bad else PASS,
                    "segredo fictício visível no sandbox" if bad else "")
        rep.add("env_extra_vars", "Variáveis adicionais no sandbox (injetadas pelo srt)", INFO,
                f"{extra}", mandatory=False)
    # Informativos: não contam como garantia (ver limitações).
    sl, hl = g("symlink_read"), g("hardlink_read")
    rep.add("symlink_native_read", "Symlink dentro da pasta autorizada apontando para fora (leitura nativa)", INFO,
            "vazou conteúdo externo" if (sl.get("ok") and fx.secret_marker in sl.get("data", ""))
            else "bloqueado nesta execução (sem garantia geral)", mandatory=False)
    if not os.path.exists(fx.hardlink):
        rep.add("hardlink_native_read", "Hardlink para decoy externo (leitura nativa)", NOT_TESTED,
                "sistema de arquivos não permitiu criar hardlink", mandatory=False)
    else:
        leak = hl.get("ok") and fx.secret_marker in hl.get("data", "")
        rep.add("hardlink_native_read", "Hardlink para decoy externo (leitura nativa)", INFO,
                "LIMITAÇÃO REPRODUZIDA: conteúdo externo legível via hardlink; Read/Edit nativos permanecem BLOCKED"
                if leak else "bloqueado nesta execução (sem garantia geral; não declarar mitigado)", mandatory=False)


def _check_pathguard(rep, fx):
    """Lógica do executor (pathguard) sobre o fixture: rejeita symlink, hardlink, '..' e absoluto.
    Isto NÃO é isolamento de processo."""
    title = "pathguard rejeita symlink, hardlink, '..' e caminho absoluto (apenas executor)"
    try:
        root_fd = pathguard.open_root(fx.authorized)
    except pathguard.PathGuardError as e:
        rep.add("pathguard_indirect", title, FAIL, f"pasta sintética recusada: {e}")
        return
    try:
        cases = [("link_to_external", "symlink"), ("../external/secret.txt", "dotdot"), (fx.secret, "absoluto")]
        if os.path.exists(fx.hardlink):
            cases.append(("hard_to_external", "hardlink"))
        bad = []
        for rel, label in cases:
            try:
                pathguard.read_bytes(root_fd, rel)
                bad.append(label)
            except pathguard.PathGuardError:
                pass
        try:
            ok = fx.auth_marker.encode() == pathguard.read_bytes(root_fd, "canary_read.txt")
        except pathguard.PathGuardError:
            ok = False
        if bad or not ok:
            rep.add("pathguard_indirect", title, FAIL, f"aceitos indevidamente: {bad}; leitura válida ok={ok}")
        else:
            rep.add("pathguard_indirect", title, PASS,
                    "" if os.path.exists(fx.hardlink) else "hardlink não testado (fs sem hardlink)")
    finally:
        os.close(root_fd)


def run_doctor(config_path, timeout=L.DEFAULT_TIMEOUT, deps=None):
    rep = Report()
    plat = sys.platform
    wsl = False
    if plat.startswith("linux"):
        try:
            with open("/proc/version", encoding="utf-8") as f:
                wsl = "microsoft" in f.read().lower()
        except OSError:
            pass
        rep.add("platform", "Plataforma", PASS if not wsl else INFO,
                "Linux" if not wsl else "WSL2 detectado: sem validação (nunca STRONG)")
    else:
        rep.add("platform", "Plataforma", FAIL, f"{plat}: não suportada nesta etapa (só Linux/Arch foi exercitado)")
    rep.add("python", "Python 3.11+", PASS if sys.version_info >= (3, 11) else FAIL, sys.version.split()[0])

    config = None
    try:
        config = isolation_config.load(config_path)
        rep.add("config", "Configuração TOML e pasta autorizada válidas", PASS)
    except isolation_config.ConfigError as e:
        rep.add("config", "Configuração TOML e pasta autorizada válidas", FAIL, str(e))
    if config:
        if config.network_mode != "deny":
            rep.add("network_policy", "Rede em deny", FAIL,
                    "allowlist não é liberada no PR3 (exige validação específica)")
        else:
            rep.add("network_policy", "Rede em deny", PASS)
        if config.auth_mode != "none":
            rep.add("auth_mode", "Modo de autenticação", INFO,
                    f"{config.auth_mode}: processo autenticado fora da fronteira, não é isolamento integral",
                    mandatory=False)

    blocking_so_far = any(c["status"] == FAIL for c in rep.checks)
    if deps is None and not blocking_so_far:
        deps = L.detect_dependencies()
    if deps is not None:
        for name in ("srt", "node", "bwrap", "socat", "rg"):
            d = deps.get(name)
            rep.add(f"dep_{name}", f"Dependência {name}", PASS if d.ok else FAIL,
                    " ".join(x for x in (d.version, d.reason) if x) or "")
    try:
        reads = L.runtime_read_paths() if deps is not None else []
        if deps is not None:
            rep.add("runtime_reads", "Leitura mínima do runtime (justificada)", PASS, ", ".join(reads))
    except L.LauncherError as e:
        reads = []
        rep.add("runtime_reads", "Leitura mínima do runtime (justificada)", FAIL, str(e))

    prereq_ok = (config is not None and not any(c["status"] == FAIL for c in rep.checks)
                 and deps is not None and deps.all_ok)
    all_ids = [("canary_run", dict(CANARY_CHECKS)["canary_run"])] + [c for c in CANARY_CHECKS if c[0] != "canary_run"]
    fail_closed_ids = [("fail_closed_missing_settings", "srt recusa política ausente (sem execução sem sandbox)"),
                       ("fail_closed_invalid_settings", "srt recusa política inválida (sem execução sem sandbox)")]
    if not prereq_ok:
        rep.not_tested(all_ids + fail_closed_ids,
                       "pré-requisitos falharam (ver checks acima); nenhum canário foi executado")
        if config is not None and plat.startswith("linux"):
            with L.create_fixture() as fx:  # lógica do executor, sem sandbox
                _check_pathguard(rep, fx)
        else:
            rep.add("pathguard_indirect", "pathguard em caminhos indiretos", NOT_TESTED, "plataforma/config inválida")
    else:
        sentinel = "FAKE-SECRET-" + os.urandom(6).hex()
        prev = os.environ.get("TOOLKIT_DOCTOR_FAKE_SECRET")
        os.environ["TOOLKIT_DOCTOR_FAKE_SECRET"] = sentinel
        try:
            with L.create_fixture() as fx, L.TcpListeners() as lst:
                lst.control_ok = {k: lst.host_control(k) for k in lst.socks}
                for k in lst.hits:
                    lst.hits[k] = 0
                _check_pathguard(rep, fx)
                synth = dataclasses.replace(config, authorized_dir=fx.authorized, auth_mode="none")
                try:
                    res = L.run_suite(deps, synth, fx, lst.target("loopback"), lst.target("external"),
                                      os.getpid(), sentinel, timeout)
                except L.LauncherError as e:
                    res = L.SuiteResult(False, str(e))
                if not res.ran:
                    rep.add("canary_run", dict(CANARY_CHECKS)["canary_run"], FAIL,
                            f"{res.reason} (código={res.returncode}, timeout={res.timed_out}); "
                            f"stderr: {res.stderr_tail[-400:]!r}")
                    rep.not_tested([c for c in CANARY_CHECKS if c[0] != "canary_run"],
                                   "a suíte não executou: nada foi comprovado")
                else:
                    rep.add("canary_run", dict(CANARY_CHECKS)["canary_run"], PASS)
                    _check_canaries(rep, fx, res, lst, os.environ.get("TOOLKIT_DOCTOR_FAKE_SECRET") == sentinel)
                for kind, (cid, title) in zip(("missing", "invalid"), fail_closed_ids):
                    try:
                        fc = L.run_fail_closed_probe(deps, fx, kind, timeout)
                    except L.LauncherError as e:
                        rep.add(cid, title, FAIL, str(e))
                        continue
                    if fc.ran or os.path.exists(fx.auth_write + "." + kind):
                        rep.add(cid, title, FAIL, "o comando executou sem a política válida")
                    elif fc.timed_out:
                        rep.add(cid, title, NOT_TESTED, "timeout: sem evidência")
                    elif fc.returncode in (None, 0):
                        rep.add(cid, title, FAIL, "srt terminou com sucesso sem executar o canário")
                    else:
                        rep.add(cid, title, PASS)
        finally:
            if prev is None:
                os.environ.pop("TOOLKIT_DOCTOR_FAKE_SECRET", None)
            else:
                os.environ["TOOLKIT_DOCTOR_FAKE_SECRET"] = prev

    mand = [c for c in rep.checks if c["mandatory"]]
    failed = [c for c in mand if c["status"] == FAIL]
    untested = [c for c in mand if c["status"] == NOT_TESTED]
    canaries = "FAILED" if failed else ("INCOMPLETE" if untested else "PASSED")
    reasons = [f"{c['id']}: {c['status']} {c['reason']}".strip() for c in failed]
    if untested:
        reasons.append(f"{len(untested)} checks NOT_TESTED: " + ", ".join(c["id"] for c in untested))
    reasons.append("STRONG indisponível no PR3 (critérios da ADR-011 pendentes); operações com arquivos permanecem BLOCKED "
                   "mesmo com canários PASSED")
    if config is None or not plat.startswith("linux"):
        code = 3
    else:
        code = 0 if canaries == "PASSED" else 2
    return {
        "schema": 1,
        "platform": plat + (" (WSL2)" if wsl else ""),
        "supported": {"srt": L.SUPPORTED_SRT_VERSION, "bwrap_min": ".".join(map(str, L.MIN_BWRAP)),
                      "bwrap_validated": L.VALIDATED_BWRAP, "python": ">=3.11"},
        "checks": rep.checks,
        "summary": {
            "sandbox_canaries": canaries,
            "file_operations": "BLOCKED",
            "strong": "UNAVAILABLE",
            "advisory": "somente se escolhido explicitamente, sem ferramentas de arquivo; nunca fallback automático",
            "agent_execution_authorized": False,
            "reasons": reasons,
        },
        "limitations": list(LIMITATIONS),
        "exit_code": code,
    }


def render_text(report):
    lines = ["Toolkit doctor (PR3) — diagnóstico do SRT; NÃO autoriza executar agentes", ""]
    for c in report["checks"]:
        extra = f" — {c['reason']}" if c["reason"] else ""
        lines.append(f"[{c['status']:<10}] {c['title']}{extra}")
    s = report["summary"]
    lines += ["", f"Canários do sandbox : {s['sandbox_canaries']}",
              f"Operações c/ arquivos: {s['file_operations']}",
              f"STRONG               : {s['strong']}",
              f"Execução de agentes  : {'autorizada' if s['agent_execution_authorized'] else 'NÃO autorizada'}",
              "", "Motivos:"] + [f"  - {r}" for r in s["reasons"]]
    lines += ["", "Limitações não demonstradas:"] + [f"  - {x}" for x in report["limitations"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Toolkit doctor (diagnóstico; não libera agentes)")
    ap.add_argument("--config", required=True, help="caminho explícito do TOML de configuração")
    ap.add_argument("--json", action="store_true", help="saída JSON estruturada")
    ap.add_argument("--timeout", type=int, default=L.DEFAULT_TIMEOUT, help="timeout por execução no srt (s)")
    args = ap.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        ap.error("--timeout deve estar entre 1 e 300")
    rep = run_doctor(args.config, args.timeout)
    print(json.dumps(rep, indent=2, ensure_ascii=False) if args.json else render_text(rep))
    return rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
