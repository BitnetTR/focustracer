# Installation

FocusTracer requires **Python 3.10+** and is distributed from GitHub (it is not published on PyPI).

Repository: `https://github.com/BitnetTR/focustracer`

## 1. Install from git (recommended for users)

```bash
pip install "git+https://github.com/BitnetTR/focustracer.git"
```

This installs the latest `master`, all runtime dependencies and the `focustracer` console command.
The web UI frontend is shipped pre-built inside the package, so Node.js is **not** required.

### Pin a branch, tag or commit

Append `@<ref>` to the URL:

```bash
# branch
pip install "git+https://github.com/BitnetTR/focustracer.git@master"

# tag
pip install "git+https://github.com/BitnetTR/focustracer.git@v1.6.0"

# exact commit
pip install "git+https://github.com/BitnetTR/focustracer.git@<commit-sha>"
```

Available tags: `git ls-remote --tags https://github.com/BitnetTR/focustracer.git`.

### SSH (private access / no HTTPS credentials)

```bash
pip install "git+ssh://git@github.com/BitnetTR/focustracer.git@master"
```

## 2. Use as a dependency of another project

`requirements.txt`:

```text
focustracer @ git+https://github.com/BitnetTR/focustracer.git@master
```

`pyproject.toml`:

```toml
[project]
dependencies = [
    "focustracer @ git+https://github.com/BitnetTR/focustracer.git@master",
]
```

Pinning to a tag or commit instead of `master` gives reproducible builds.

## 3. Editable install straight from git

Clones the repository and installs it in editable mode in one step, so you can modify the source:

```bash
pip install -e "git+https://github.com/BitnetTR/focustracer.git@master#egg=focustracer"
```

pip clones the sources into `./src/focustracer` (relative to the current directory).
Use `--src <dir>` to choose another location:

```bash
pip install --src ./vendor -e "git+https://github.com/BitnetTR/focustracer.git@master#egg=focustracer"
```

## 4. Development install from a local clone

```bash
git clone https://github.com/BitnetTR/focustracer.git
cd focustracer
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e .
pip install pytest
python -m pytest
```

## 5. Verify

```bash
focustracer --help
python -m focustracer --help
python -c "import focustracer; print(focustracer.__file__)"
```

## 6. Upgrade / reinstall

pip does not always rebuild a git install whose version number has not changed. Force it:

```bash
pip install --upgrade --force-reinstall --no-deps "git+https://github.com/BitnetTR/focustracer.git@master"
```

For an editable install, just `git pull` inside the cloned directory.

## 7. Uninstall

```bash
pip uninstall focustracer
```

## 8. Optional: LLM backend

Tracing, `load`, `slice`, `reverse`, `replay` and `align` work fully offline.
Only `suggest-targets`, `run --auto-targets` and `explain` need an LLM backend
(Ollama or OpenCode). See [llm-agents.md](./llm-agents.md). The `install` command can guide you:

```bash
python -m focustracer install --status
python -m focustracer install --agent ollama
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `git` not found | Install Git and make sure it is on `PATH`; pip needs it for `git+` URLs. |
| Authentication prompt / 403 | Use the SSH form, or a GitHub token: `git+https://<token>@github.com/BitnetTR/focustracer.git`. Do not commit tokens into requirements files. |
| `focustracer` command not found | The Python `Scripts`/`bin` directory is not on `PATH`; use `python -m focustracer` instead. |
| `lxml` build error | Upgrade pip (`python -m pip install -U pip`) so a pre-built wheel is used. |
| Old code after reinstall | Use `--force-reinstall --no-deps` (section 6). |
