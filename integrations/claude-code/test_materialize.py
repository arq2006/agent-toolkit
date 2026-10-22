#!/usr/bin/env python3
"""Testes negativos do gerador. Escrevem só em diretório temporário descartável.

Executar: python3 -I integrations/claude-code/test_materialize.py
"""
import contextlib, importlib.util, io, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("materialize", HERE / "materialize.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def run(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = M.main(["--root", str(root), *args])
    return rc, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name) / "repo"
        shutil.copytree(REPO / "agents", self.root / "agents")
        shutil.copytree(REPO / "integrations/claude-code", self.root / "integrations/claude-code",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.outside = Path(self._t.name) / "outside"
        self.outside.mkdir()

    def mapping(self, fn):
        p = self.root / "integrations/claude-code/mapping.yaml"
        d = yaml.safe_load(p.read_text())
        fn(d["agents"])
        p.write_text(yaml.safe_dump(d))

    def agents_dir(self):
        return self.root / ".claude/agents"


class Materialize(Base):
    def test_dry_run_writes_nothing(self):
        rc, out, _ = run(self.root, "agents")
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / ".claude").exists())

    def test_write_only_read_only_agents(self):
        rc, _, _ = run(self.root, "agents", "--write")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in self.agents_dir().iterdir()), ["auditor.md", "planner.md"])

    def test_divergent_refused_and_no_partial(self):
        (self.agents_dir()).mkdir(parents=True)
        (self.agents_dir() / "planner.md").write_text("manual\n")
        rc, out, _ = run(self.root, "agents", "--write")
        self.assertEqual(rc, 1)
        self.assertEqual((self.agents_dir() / "planner.md").read_text(), "manual\n")
        self.assertFalse((self.agents_dir() / "auditor.md").exists())
        self.assertIn("NADA gravado", out)

    def test_extra_tool_on_read_only_rejected(self):
        for tool in ("Bash", "Write", "Foo"):
            with self.subTest(tool=tool):
                self.mapping(lambda a: a["planner"]["tools"].append(tool))
                rc, out, _ = run(self.root, "agents", "--write")
                self.assertEqual(rc, 1)
                self.assertFalse((self.root / ".claude").exists())
                shutil.copy(REPO / "integrations/claude-code/mapping.yaml", self.root / "integrations/claude-code/mapping.yaml")

    def test_missing_tool_or_unknown_key_rejected(self):
        self.mapping(lambda a: a["planner"].update(permissionMode="bypassPermissions"))
        self.assertEqual(run(self.root, "agents")[0], 1)
        shutil.copy(REPO / "integrations/claude-code/mapping.yaml", self.root / "integrations/claude-code/mapping.yaml")
        self.mapping(lambda a: a["planner"].update(tools=["Read"]))
        self.assertEqual(run(self.root, "agents")[0], 1)

    def test_bad_names_and_traversal(self):
        for name in ("../evil", "Planner", "a/b", "x" * 60, ""):
            with self.subTest(name=name):
                self.mapping(lambda a, n=name: a.update({n: dict(a["planner"])}))
                rc, out, _ = run(self.root, "agents", "--write")
                self.assertEqual(rc, 1)
                self.assertFalse((self.root / ".claude").exists())
                self.assertEqual(list(self.outside.iterdir()), [])
                shutil.copy(REPO / "integrations/claude-code/mapping.yaml", self.root / "integrations/claude-code/mapping.yaml")

    def test_symlinked_dirs_and_files_refused(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude/agents").symlink_to(self.outside)
        self.assertEqual(run(self.root, "agents", "--write")[0], 1)
        self.assertEqual(list(self.outside.iterdir()), [])
        (self.root / ".claude/agents").unlink()
        (self.root / ".claude").rmdir()
        (self.root / ".claude").symlink_to(self.outside)
        self.assertEqual(run(self.root, "agents", "--write")[0], 1)
        self.assertEqual(list(self.outside.iterdir()), [])
        (self.root / ".claude").unlink()
        self.agents_dir().mkdir(parents=True)
        (self.agents_dir() / "planner.md").symlink_to(self.outside / "target.md")
        self.assertEqual(run(self.root, "agents", "--write")[0], 1)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_symlinked_source_refused(self):
        src = self.root / "agents/planner/AGENT.md"
        real = self.outside / "AGENT.md"
        shutil.move(src, real)
        src.symlink_to(real)
        self.assertEqual(run(self.root, "agents", "--write")[0], 1)
        self.assertFalse((self.root / ".claude").exists())

    def test_implementer_never_materialized(self):
        self.mapping(lambda a: a["implementer"].update(materialize=True))
        rc, out, _ = run(self.root, "agents", "--write")
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / ".claude").exists())
        shutil.copy(REPO / "integrations/claude-code/mapping.yaml", self.root / "integrations/claude-code/mapping.yaml")
        run(self.root, "agents", "--write")
        self.assertFalse((self.agents_dir() / "implementer.md").exists())

    def test_source_contract_inconsistent_rejected(self):
        p = self.root / "agents/planner/AGENT.md"
        for old, new in (("level: A0}\n  - {op: analyze_diff", "level: A1}\n  - {op: analyze_diff"),
                         ("file_scope: none", "file_scope: all"), ("  - write_files\n", "")):
            with self.subTest(old=old):
                orig = p.read_text()
                self.assertIn(old, orig)
                p.write_text(orig.replace(old, new, 1))
                self.assertEqual(run(self.root, "agents", "--write")[0], 1)
                self.assertFalse((self.root / ".claude").exists())
                p.write_text(orig)

    def test_yaml_special_characters_round_trip(self):
        desc = 'Use: quando "aspas", \'simples\', # hash, {chaves}, [lista], - traço, & e * e !tag? Também: dois-pontos\ncom quebra'
        self.mapping(lambda a: a["planner"].update(description=desc))
        self.assertEqual(run(self.root, "agents", "--write")[0], 0)
        text = (self.agents_dir() / "planner.md").read_text()
        meta = yaml.safe_load(text.split("---\n")[1])
        self.assertEqual(meta["description"], " ".join(desc.split()))
        self.assertEqual(meta["tools"], "Read, Grep, Glob")
        self.assertEqual(set(meta), {"name", "description", "tools", "disallowedTools", "model", "effort"})


class Symlinks(Base):
    def external_copy(self, rel):
        """Move root/rel para fora e deixa um link simbólico no lugar."""
        src = self.root / rel
        dst = self.outside / rel.replace("/", "_")
        shutil.move(src, dst)
        src.symlink_to(dst)
        return dst

    def assert_refused(self):
        rc, out, err = run(self.root, "agents", "--write")
        self.assertNotEqual(rc, 0, out)
        self.assertFalse((self.root / ".claude").exists())

    def test_agents_dir_symlink_to_external_dir(self):
        self.external_copy("agents")
        self.assert_refused()

    def test_agent_subdir_symlink_to_external_dir(self):
        self.external_copy("agents/planner")
        self.assert_refused()

    def test_integrations_dir_symlink(self):
        self.external_copy("integrations")
        self.assert_refused()

    def test_mapping_file_symlink(self):
        self.external_copy("integrations/claude-code/mapping.yaml")
        self.assert_refused()


class WriteRecovery(Base):
    def test_io_failure_rolls_back_only_created_files(self):
        run(self.root, "agents", "--write")
        planner = self.agents_dir() / "planner.md"
        (self.agents_dir() / "auditor.md").unlink()
        before = planner.read_text()
        calls = []
        real = M.write_new

        def flaky(out, text):
            calls.append(out.name)
            raise OSError("falha simulada")
        M.write_new = flaky
        try:
            rc, out, _ = run(self.root, "agents", "--write")
        finally:
            M.write_new = real
        self.assertEqual(rc, 2)
        self.assertEqual(planner.read_text(), before)  # preexistente intacto
        self.assertFalse((self.agents_dir() / "auditor.md").exists())

    def test_failure_after_first_file_removes_it(self):
        real = M.write_new
        n = []

        def second_fails(out, text):
            n.append(1)
            if len(n) == 2:
                raise OSError("falha simulada")
            real(out, text)
        M.write_new = second_fails
        try:
            rc, out, _ = run(self.root, "agents", "--write")
        finally:
            M.write_new = real
        self.assertEqual(rc, 2)
        self.assertEqual(list(self.agents_dir().glob("*")), [])

    def test_rerun_is_idempotent_and_never_overwrites(self):
        self.assertEqual(run(self.root, "agents", "--write")[0], 0)
        first = {p.name: p.read_text() for p in self.agents_dir().iterdir()}
        self.assertEqual(run(self.root, "agents", "--write")[0], 0)
        self.assertEqual(first, {p.name: p.read_text() for p in self.agents_dir().iterdir()})

    def test_write_new_refuses_existing_file(self):
        self.agents_dir().mkdir(parents=True)
        f = self.agents_dir() / "x.md"
        f.write_text("antigo")
        with self.assertRaises(FileExistsError):
            M.write_new(f, "novo")
        self.assertEqual(f.read_text(), "antigo")
        self.assertEqual([p.name for p in self.agents_dir().iterdir()], ["x.md"])  # sem temporário sobrando


class GitState(Base):
    def git(self, *a):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull)
        subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True, env=env)

    def test_untracked_content_change_detected_without_exposing_content(self):
        self.git("init", "-q"); self.git("add", "agents"); self.git("commit", "-q", "-m", "x")
        secret = "CONTEUDO-FICTICIO-12345"
        (self.root / "novo.txt").write_text(secret + "a")
        rc, a, _ = run(self.root, "git-state")
        (self.root / "novo.txt").write_text(secret + "b")
        rc2, b, _ = run(self.root, "git-state")
        self.assertEqual((rc, rc2), (0, 0))
        self.assertNotIn(secret, a + b)
        pa, pb = Path(self._t.name) / "a.json", Path(self._t.name) / "b.json"
        pa.write_text(a); pb.write_text(b)
        self.assertEqual(run(self.root, "compare", str(pa), str(pb))[0], 1)
        self.assertEqual(run(self.root, "compare", str(pa), str(pa))[0], 0)
        self.assertIn("novo.txt", json.loads(a)["untracked_sha256"])

    def test_git_failure_is_error(self):
        rc, out, err = run(self.root, "git-state")  # diretório sem repositório Git
        self.assertEqual(rc, 2)
        self.assertIn("ERRO", err)
        self.assertEqual(out, "")


    def tree_fingerprint(self):
        out = {}
        for p in sorted(self.root.rglob("*")):
            if ".git" in p.parts or p.is_dir():
                continue
            out[str(p.relative_to(self.root))] = M.file_sha256(p)
        return out

    def test_full_flow_snapshots_outside_tree_are_identical(self):
        self.git("init", "-q"); self.git("add", "agents"); self.git("commit", "-q", "-m", "x")
        (self.root / "novo.txt").write_text("fictício")
        snap = Path(self._t.name) / "snaps"
        snap.mkdir(mode=0o700)
        before = self.tree_fingerprint()
        a, b = snap / "inicial.json", snap / "final.json"
        self.assertEqual(run(self.root, "git-state", "--out", str(a))[0], 0)
        self.assertEqual(run(self.root, "git-state", "--out", str(b))[0], 0)
        self.assertEqual(run(self.root, "compare", str(a), str(b))[0], 0)
        self.assertEqual(a.read_text(), b.read_text())
        self.assertEqual(before, self.tree_fingerprint())  # nada novo na árvore
        self.assertEqual(oct(a.stat().st_mode & 0o777), "0o600")
        self.assertNotIn("fictício", a.read_text())

    def test_snapshot_inside_repo_or_open_dir_refused(self):
        self.git("init", "-q"); self.git("add", "agents"); self.git("commit", "-q", "-m", "x")
        rc, _, err = run(self.root, "git-state", "--out", str(self.root / "inicial.json"))
        self.assertEqual(rc, 2)
        self.assertFalse((self.root / "inicial.json").exists())
        open_dir = Path(self._t.name) / "aberto"
        open_dir.mkdir(mode=0o755)
        os.chmod(open_dir, 0o755)
        self.assertEqual(run(self.root, "git-state", "--out", str(open_dir / "s.json"))[0], 2)
        self.assertFalse((open_dir / "s.json").exists())

    def test_snapshot_never_overwrites_existing(self):
        self.git("init", "-q"); self.git("add", "agents"); self.git("commit", "-q", "-m", "x")
        snap = Path(self._t.name) / "snaps"
        snap.mkdir(mode=0o700)
        (snap / "s.json").write_text("antigo")
        self.assertEqual(run(self.root, "git-state", "--out", str(snap / "s.json"))[0], 2)
        self.assertEqual((snap / "s.json").read_text(), "antigo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
