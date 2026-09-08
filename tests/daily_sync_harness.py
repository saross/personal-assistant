"""
Behavioural test harness for ``scripts/daily-sync.sh``.

Why this exists
---------------
Audit 2026-09-08 (Lens B, finding C1) established that ``daily-sync.sh``
had no behavioural test at all: its single end-to-end fixture died at the
parent stash before reaching the sync body, and the test passed anyway.
Nine one-line mutations of load-bearing logic — including "never push
again" and "silently discard the other machine's memory records" —
survived the whole suite.

This module builds a small world the script can actually be run in:

* a bare ``parent.git`` and a bare ``data.git`` standing in for GitHub;
* one or more *machines*, each a full clone of the parent with the data
  submodule initialised, so cross-machine races can be staged;
* a stub ``PATH`` in which ``ssh``, ``sshfs``, ``rsync``, ``rclone``,
  ``scp``, and ``fusermount`` all fail fast, so no test can reach the
  network (audit S21);
* stubs for the helper scripts ``daily-sync.sh`` shells out to
  (``archive-agent-mail.py``, ``check-memory-drift.py``,
  ``check-archive-drift.py``, ``sync-symlinks.sh``,
  ``push-archives-to-r2.sh``), each of which records its invocation and
  exits with a code the test chooses. The scripts genuinely under test —
  ``daily-sync.sh`` itself and ``resolve-merge-conflicts.py`` — are
  symlinked in live.

``HOME`` is pinned to a directory inside ``tmp_path`` for every run, so
``~/.claude``, ``~/.cache``, ``~/cc-archives``, and ``~/mnt/rpi-shares``
all resolve inside the sandbox (audit S21). Nothing here writes outside
``tmp_path``.

Fixture fidelity notes
----------------------
The parent repo carries the ``.gitignore`` that production has, so
``git stash push -u`` in the parent does not sweep ``logs/`` (the exact
divergence that killed the previous fixture mid-run). ``logs/`` is a real
directory rather than the production ``logs -> data/logs`` symlink; the
observable behaviour — git never sees it — is the same.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SCRIPTS = REPO_ROOT / "scripts"

#: Scripts that are the subject of these tests and must run for real.
LIVE_SCRIPTS = ("daily-sync.sh", "resolve-merge-conflicts.py")

#: Binaries stubbed out to make network egress impossible (audit S21).
OFFLINE_BINARIES = ("ssh", "sshfs", "rsync", "rclone", "scp", "fusermount")

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test Bot",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Bot",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    # Local-path submodules are refused by default since the 2022
    # advisories; every repo here is a throwaway under tmp_path.
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
}

_PY_STUB_TEMPLATE = '''#!/usr/bin/env python3
"""Test stub for {name} — records the call, exits with a chosen code."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Record the invocation and return the configured exit code."""
    log = os.environ.get("PA_TEST_CALL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("{name} " + " ".join(sys.argv[1:]) + "\\n")
{body}
    return int(os.environ.get("{rc_var}", "0"))


if __name__ == "__main__":
    sys.exit(main())
'''

#: archive-agent-mail.py commits into the data submodule. Reproduce that
#: when a test asks for it, so "its commit is pushed by the sync" can be
#: asserted rather than assumed.
_ARCHIVER_STUB_BODY = '''
    # The archiver runs between the branch-switch stash and the pre-pull
    # stash, which makes it the natural place to simulate anything that
    # dirties the tree in that window — a concurrent session writing prose,
    # or the archiver itself leaving files behind (audit C1).
    dirties = os.environ.get("PA_TEST_ARCHIVER_DIRTIES")
    if dirties:
        data = Path(__file__).resolve().parent.parent / "data"
        (data / "tasks" / "inbox.md").write_text(dirties, encoding="utf-8")

    # A concurrent session pushing its OWN stash between the run's push
    # and its pop — the race the SHA bookkeeping exists for.
    foreign = os.environ.get("PA_TEST_ARCHIVER_STASHES")
    if foreign:
        data = Path(__file__).resolve().parent.parent / "data"
        (data / "tasks" / "foreign-session.md").write_text(foreign, encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(data), "stash", "push", "-u", "-q",
             "-m", "a concurrent session", "--", "tasks/foreign-session.md"],
            check=True,
        )

    marker = os.environ.get("PA_TEST_ARCHIVER_COMMIT")
    if marker:
        data = Path(__file__).resolve().parent.parent / "data"
        relative = "agent-mail/index.jsonl"
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(marker + "\\n")
        subprocess.run(["git", "-C", str(data), "add", "--", relative], check=True)
        subprocess.run(
            ["git", "-C", str(data), "commit", "-q", "-m",
             "chore(agent-mail): archive", "--", relative],
            check=True,
        )
'''

#: check-memory-drift.py doubles as the orphan-stash oracle, so its stub
#: answers --list-recoverable-stashes from an environment variable.
_DRIFT_STUB_BODY = '''
    if "--list-recoverable-stashes" in sys.argv:
        refs = os.environ.get("PA_TEST_ORPHAN_STASHES", "")
        for ref in [r for r in refs.split(",") if r]:
            print(ref)
        sys.stdout.flush()
        # A concurrent session pushing a stash AFTER the detector has
        # reported, i.e. between the caller resolving those selectors and
        # acting on them. The pause lets the caller's resolution land
        # first: it happens microseconds after the flush above, so the
        # ordering is deterministic in practice even though the two
        # processes are not synchronised.
        # A concurrent session dropping the very entry just reported, so
        # the caller's apply still works (the commit outlives the entry)
        # but its drop finds nothing.
        if os.environ.get("PA_TEST_DRIFT_DROPS_AFTER"):
            import time

            time.sleep(0.3)
            data = Path(__file__).resolve().parent.parent / "data"
            subprocess.run(
                ["git", "-C", str(data), "stash", "drop", "-q",
                 os.environ["PA_TEST_DRIFT_DROPS_AFTER"]],
                check=True,
            )

        racing = os.environ.get("PA_TEST_DRIFT_STASHES_AFTER")
        if racing:
            import time

            time.sleep(0.3)
            data = Path(__file__).resolve().parent.parent / "data"
            (data / "tasks" / "racing.md").write_text(racing, encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(data), "stash", "push", "-u", "-q",
                 "-m", "a concurrent session", "--", "tasks/racing.md"],
                check=True,
            )
        return 0
'''

_SH_STUB_TEMPLATE = """#!/usr/bin/env bash
# Test stub for {name} — records the call, exits with a chosen code.
if [[ -n "${{PA_TEST_CALL_LOG:-}}" ]]; then
    printf '%s %s\\n' "{name}" "$*" >> "$PA_TEST_CALL_LOG"
fi
exit "${{{rc_var}:-0}}"
"""

_OFFLINE_STUB = """#!/usr/bin/env bash
# Audit S21: no test may reach the network.
echo "refusing to run {name} inside the test suite" >&2
exit 1
"""

_HOSTNAME_STUB = """#!/usr/bin/env bash
# Deterministic, and never the designated R2 push owner.
printf '%s\\n' "${PA_TEST_HOSTNAME:-test-machine}"
"""

_PARENT_GITIGNORE = "venv/\nlogs/\n"
_DATA_GITIGNORE = "logs/\n"


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """
    Run ``git`` in ``cwd`` with the harness's deterministic identity.

    Raises ``AssertionError`` with the captured output when ``check`` is
    set and git fails, because a silently failing setup step produces a
    baffling assertion three steps later.
    """
    env = os.environ.copy()
    env.update(_GIT_IDENTITY)
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {cwd} (rc={result.returncode})\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


@dataclass
class Machine:
    """One working machine: a parent clone with the data submodule live."""

    name: str
    pa: Path

    @property
    def data(self) -> Path:
        """Path to the machine's data submodule working copy."""
        return self.pa / "data"

    @property
    def memories(self) -> Path:
        """Path to the machine's ``memories.jsonl``."""
        return self.data / "memories" / "memories.jsonl"

    @property
    def data_git_dir(self) -> Path:
        """
        The submodule's real git directory.

        ``data/.git`` is a pointer *file* into ``<parent>/.git/modules/``,
        so hooks and internal state do not live where a top-level repo
        would put them.
        """
        return Path(git("rev-parse", "--absolute-git-dir", cwd=self.data).stdout.strip())

    def head(self, repo: str = "data") -> str:
        """Return the HEAD SHA of ``data`` or ``parent`` on this machine."""
        where = self.data if repo == "data" else self.pa
        return git("rev-parse", "HEAD", cwd=where).stdout.strip()

    def branch(self, repo: str = "data") -> str:
        """Return the current branch name (``HEAD`` when detached)."""
        where = self.data if repo == "data" else self.pa
        return git("rev-parse", "--abbrev-ref", "HEAD", cwd=where).stdout.strip()

    def racing_resolver(self, drop_selector: str = "stash@{0}") -> None:
        """
        Replace the resolver with one that drops a stash while it runs.

        The resolver subprocess is the only thing that runs between the
        conflicted apply and the drop that follows it, so it is where a
        concurrent session's `git stash drop` has to be injected to prove
        that the drop re-resolves its selector (audit C2). It still
        resolves the conflict, so the run continues normally.
        """
        target = self.pa / "scripts" / "resolve-merge-conflicts.py"
        real = REAL_SCRIPTS / "resolve-merge-conflicts.py"
        target.unlink()
        target.write_text(
            "#!/usr/bin/env python3\n"
            '"""Test stub: a concurrent session drops its stash mid-resolve."""\n'
            "import runpy\n"
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            f'data = Path(__file__).resolve().parent.parent / "data"\n'
            "# Only when actually resolving: --check is the guard's own\n"
            "# predicate and runs several times a sync.\n"
            'if "--check" not in sys.argv:\n'
            f'    subprocess.run(["git", "-C", str(data), "stash", "drop", "-q",\n'
            f'                    "{drop_selector}"], check=False)\n'
            f'sys.argv[0] = "{real}"\n'
            f'runpy.run_path("{real}", run_name="__main__")\n',
            encoding="utf-8",
        )
        target.chmod(0o755)
        git("add", "--", "scripts/resolve-merge-conflicts.py", cwd=self.pa)
        git("commit", "-q", "-m", "racing resolver", "--",
            "scripts/resolve-merge-conflicts.py", cwd=self.pa)

    def stub_resolver(self) -> None:
        """
        Replace this machine's conflict resolver with a no-op.

        "The resolver ran and did not clean the file" is exactly what the
        marker guards on the rebase paths defend against, and it cannot be
        staged with the real resolver in place. Committed, so the parent
        tree stays clean.
        """
        target = self.pa / "scripts" / "resolve-merge-conflicts.py"
        target.unlink()
        real = REAL_SCRIPTS / "resolve-merge-conflicts.py"
        target.write_text(
            "#!/usr/bin/env python3\n"
            '"""Test stub: classifies correctly, cleans nothing."""\n'
            "import runpy\n"
            "import sys\n\n"
            "# --check is the guard's shared predicate: it must keep working,\n"
            "# or this stops modelling a broken resolver and starts modelling\n"
            "# a broken guard.\n"
            'if "--check" in sys.argv:\n'
            f'    sys.argv[0] = "{real}"\n'
            f'    runpy.run_path("{real}", run_name="__main__")\n'
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        target.chmod(0o755)
        git("add", "--", "scripts/resolve-merge-conflicts.py", cwd=self.pa)
        git("commit", "-q", "-m", "stub resolver", "--",
            "scripts/resolve-merge-conflicts.py", cwd=self.pa)

    def append_memory(self, record_id: str, content: str = "note") -> str:
        """Append one record to ``memories.jsonl``, as the hook does."""
        record = {
            "id": record_id,
            "category": "decision",
            "content": content,
            "created_at": "2026-09-08T10:00:00+00:00",
        }
        with self.memories.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record_id

    def commit_data(self, message: str, *paths: str) -> str:
        """Commit ``paths`` in the data submodule and return the new SHA."""
        git("add", "--", *paths, cwd=self.data)
        git("commit", "-q", "-m", message, "--", *paths, cwd=self.data)
        return self.head()

    def push_data(self) -> None:
        """Publish the data submodule to its bare remote."""
        git("push", "-q", "origin", "main", cwd=self.data)

    def bump_and_push_parent(self, message: str = "bump data pointer") -> None:
        """Commit the submodule pointer in the parent and publish it."""
        git("add", "data", cwd=self.pa)
        git("commit", "-q", "-m", message, "--", "data", cwd=self.pa)
        git("push", "-q", "origin", "main", cwd=self.pa)


@dataclass
class SyncWorld:
    """A throwaway two-remote world in which daily-sync.sh can be run."""

    root: Path
    home: Path
    bin_dir: Path
    parent_remote: Path
    data_remote: Path
    call_log: Path
    machines: dict[str, Machine] = field(default_factory=dict)

    # -- environment ------------------------------------------------------

    def env(self, hostname: str = "test-machine", **extra: str) -> dict[str, str]:
        """
        Build the environment a sync run executes in.

        ``HOME`` and ``PATH`` are pinned (audit S21); everything else the
        caller passes in ``extra`` controls a stub's exit code.
        """
        env = os.environ.copy()
        env.update(_GIT_IDENTITY)
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
                "PA_TEST_CALL_LOG": str(self.call_log),
                "PA_TEST_HOSTNAME": hostname,
            }
        )
        env.update(extra)
        # A test may need to prove the script survives a hostile
        # environment; an empty value here means "unset it".
        for key in [k for k, v in env.items() if v == "__PA_TEST_UNSET__"]:
            del env[key]
        return env

    def run_sync(
        self,
        machine: Machine,
        *args: str,
        hostname: str | None = None,
        **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run the real ``daily-sync.sh`` on ``machine`` and capture output."""
        return subprocess.run(
            ["bash", str(machine.pa / "scripts" / "daily-sync.sh"), *args],
            cwd=str(machine.pa),
            env=self.env(hostname or machine.name, **extra),
            capture_output=True,
            text=True,
            check=False,
        )

    # -- observation ------------------------------------------------------

    def calls(self) -> list[str]:
        """Return every stub invocation recorded so far, in order."""
        if not self.call_log.exists():
            return []
        return [ln for ln in self.call_log.read_text(encoding="utf-8").splitlines() if ln]

    def calls_to(self, name: str) -> list[str]:
        """Return the recorded invocations of one stub."""
        return [ln for ln in self.calls() if ln.split(" ", 1)[0] == name]

    def published_data_head(self) -> str:
        """SHA of ``main`` in the bare data remote."""
        return git("rev-parse", "main", cwd=self.data_remote).stdout.strip()

    def published_parent_head(self) -> str:
        """SHA of ``main`` in the bare parent remote."""
        return git("rev-parse", "main", cwd=self.parent_remote).stdout.strip()

    def published_pointer(self) -> str:
        """The ``data`` gitlink SHA recorded by the published parent tree."""
        listing = git("ls-tree", "main", "data", cwd=self.parent_remote).stdout
        # Format: "160000 commit <sha>\tdata"
        return listing.split()[2] if listing.strip() else ""

    def published_data_file(self, path: str) -> str:
        """Contents of ``path`` on ``main`` in the bare data remote."""
        return git("show", f"main:{path}", cwd=self.data_remote).stdout

    def data_object_exists(self, sha: str) -> bool:
        """Is ``sha`` present in the bare data remote (i.e. fetchable)?"""
        return git("cat-file", "-e", sha, cwd=self.data_remote, check=False).returncode == 0

    def gate(self, name: str) -> str:
        """Read one of the ``~/.cache`` gate files, or '' if absent."""
        path = self.home / ".cache" / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def publish_parent_change(
        self, path: str, content: str, message: str = "parent change from elsewhere"
    ) -> str:
        """Push a parent-repo change as another machine (or GitHub) would."""
        scratch = self.root / "parent-publisher"
        if scratch.exists():
            git("pull", "-q", "--ff-only", "origin", "main", cwd=scratch)
        else:
            git("clone", "-q", "--no-checkout", str(self.parent_remote), str(scratch),
                cwd=self.root)
            git("read-tree", "-m", "-u", "HEAD", cwd=scratch)
        target = scratch / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git("add", "--", path, cwd=scratch)
        git("commit", "-q", "-m", message, "--", path, cwd=scratch)
        git("push", "-q", "origin", "main", cwd=scratch)
        return git("rev-parse", "HEAD", cwd=scratch).stdout.strip()

    def _publisher(self) -> Path:
        """A scratch clone of the data remote, standing in for machine B."""
        scratch = self.root / "publisher"
        if scratch.exists():
            git("pull", "-q", "--ff-only", "origin", "main", cwd=scratch)
        else:
            git("clone", "-q", str(self.data_remote), str(scratch), cwd=self.root)
        return scratch

    def publish_memory_append(
        self, record_id: str, content: str = "from the other machine"
    ) -> str:
        """
        Append a record to ``memories.jsonl`` on the remote.

        This is what the other machine's extraction hook plus its own
        daily-sync produce, and it is the conflict the whole append-safe
        resolution path exists for.
        """
        scratch = self._publisher()
        record = {
            "id": record_id,
            "category": "decision",
            "content": content,
            "created_at": "2026-09-08T09:00:00+00:00",
        }
        with (scratch / "memories" / "memories.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        git("add", "--", "memories/memories.jsonl", cwd=scratch)
        git("commit", "-q", "-m", f"append {record_id}", "--",
            "memories/memories.jsonl", cwd=scratch)
        git("push", "-q", "origin", "main", cwd=scratch)
        return record_id

    def publish_data_change(
        self, path: str, content: str, message: str = "change from another machine"
    ) -> str:
        """
        Push a change to the data remote as another machine would have.

        Uses a scratch clone kept for the life of the world, so several
        foreign pushes can be staged in sequence.
        """
        scratch = self._publisher()
        target = scratch / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git("add", "--", path, cwd=scratch)
        git("commit", "-q", "-m", message, "--", path, cwd=scratch)
        git("push", "-q", "origin", "main", cwd=scratch)
        return git("rev-parse", "HEAD", cwd=scratch).stdout.strip()

    # -- construction -----------------------------------------------------

    def add_machine(self, name: str) -> Machine:
        """Clone the published parent into a new machine and initialise it."""
        pa = self.root / "machines" / name / "pa"
        pa.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", str(self.parent_remote), str(pa), cwd=self.root)
        git("submodule", "update", "--init", "--quiet", cwd=pa)
        # `submodule update` checks the recorded SHA out detached; normal
        # production state is the submodule sitting on main.
        git("checkout", "-q", "main", cwd=pa / "data")
        (pa / "logs").mkdir(exist_ok=True)
        venv_bin = pa / "venv" / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / "python3").symlink_to("/usr/bin/python3")
        machine = Machine(name=name, pa=pa)
        self.machines[name] = machine
        return machine


def _write_stub(path: Path, body: str) -> None:
    """Write an executable stub script."""
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _build_scripts_dir(scripts: Path) -> None:
    """Populate a machine's ``scripts/`` with live scripts plus stubs."""
    scripts.mkdir(parents=True, exist_ok=True)
    for name in LIVE_SCRIPTS:
        (scripts / name).symlink_to(REAL_SCRIPTS / name)
    for name, rc_var, extra in (
        ("archive-agent-mail.py", "PA_TEST_ARCHIVER_RC", _ARCHIVER_STUB_BODY),
        ("check-memory-drift.py", "PA_TEST_DRIFT_RC", _DRIFT_STUB_BODY),
        ("check-archive-drift.py", "PA_TEST_ARCHIVE_DRIFT_RC", ""),
    ):
        _write_stub(
            scripts / name,
            _PY_STUB_TEMPLATE.format(name=name, rc_var=rc_var, body=extra),
        )
    for name, rc_var in (
        ("sync-symlinks.sh", "PA_TEST_SYMLINKS_RC"),
        ("compose-global-claude-md.sh", "PA_TEST_COMPOSE_RC"),
        ("push-archives-to-r2.sh", "PA_TEST_R2_RC"),
    ):
        _write_stub(scripts / name, _SH_STUB_TEMPLATE.format(name=name, rc_var=rc_var))


def _build_offline_bin(bin_dir: Path) -> None:
    """Populate the stub ``PATH`` directory (audit S21)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in OFFLINE_BINARIES:
        _write_stub(bin_dir / name, _OFFLINE_STUB.format(name=name))
    _write_stub(bin_dir / "hostname", _HOSTNAME_STUB)


def build_world(tmp_path: Path) -> SyncWorld:
    """
    Build the bare remotes and the seeded template, ready for machines.

    Call ``world.add_machine("a")`` afterwards for each machine the test
    needs. The template's data submodule already holds one memory record,
    a tag vocabulary, a prose file (``tasks/inbox.md`` — the file class
    the automatic resolver must never touch), and ``config/sync.json``.
    """
    root = tmp_path / "world"
    root.mkdir()
    home = root / "home"
    (home / ".cache").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    bin_dir = root / "bin"
    _build_offline_bin(bin_dir)

    parent_remote = root / "parent.git"
    data_remote = root / "data.git"
    for remote in (parent_remote, data_remote):
        remote.mkdir()
        git("init", "--bare", "--quiet", "--initial-branch=main", cwd=remote)

    # Seed the data repository.
    data_src = root / "seed-data"
    data_src.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=data_src)
    (data_src / "memories").mkdir()
    (data_src / "memories" / "memories.jsonl").write_text(
        json.dumps(
            {
                "id": "2026-09-01-seed",
                "category": "decision",
                "content": "seed record",
                "created_at": "2026-09-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (data_src / "memories" / "tag-vocabulary.txt").write_text("seed-tag\n", encoding="utf-8")
    (data_src / "tasks").mkdir()
    (data_src / "tasks" / "inbox.md").write_text("# Inbox\n\n- seed item\n", encoding="utf-8")
    (data_src / "config").mkdir()
    (data_src / "config" / "sync.json").write_text("{}\n", encoding="utf-8")
    (data_src / ".gitignore").write_text(_DATA_GITIGNORE, encoding="utf-8")
    git("add", "-A", cwd=data_src)
    git("commit", "-q", "-m", "seed data", cwd=data_src)
    git("remote", "add", "origin", str(data_remote), cwd=data_src)
    git("push", "-q", "origin", "main", cwd=data_src)

    # Seed the parent repository.
    parent_src = root / "seed-parent"
    parent_src.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=parent_src)
    (parent_src / ".gitignore").write_text(_PARENT_GITIGNORE, encoding="utf-8")
    # A tracked, per-machine parent file — the shape production's
    # settings.json has, and the one the parent stash is there for.
    (parent_src / "settings.json").write_text("{}\n", encoding="utf-8")
    _build_scripts_dir(parent_src / "scripts")
    git("add", "-A", cwd=parent_src)
    git("commit", "-q", "-m", "seed parent", cwd=parent_src)
    git("submodule", "add", "--quiet", str(data_remote), "data", cwd=parent_src)
    git("commit", "-q", "-m", "add data submodule", cwd=parent_src)
    git("remote", "add", "origin", str(parent_remote), cwd=parent_src)
    git("push", "-q", "origin", "main", cwd=parent_src)

    return SyncWorld(
        root=root,
        home=home,
        bin_dir=bin_dir,
        parent_remote=parent_remote,
        data_remote=data_remote,
        call_log=root / "stub-calls.log",
    )
