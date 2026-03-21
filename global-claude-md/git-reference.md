## Git — Full Reference

### Commit Types

| Type | Purpose |
|------|---------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace (no code change) |
| `refactor` | Code restructuring (no behaviour change) |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `build` | Build system or dependencies |
| `chore` | Maintenance tasks, tooling |

### Gitignore Policy

Be **cautious and conservative** when adding entries to `.gitignore`. Only
ignore files that genuinely should not be tracked:

| Should Ignore | Examples | Reason |
|---------------|----------|--------|
| Sensitive/private files | `.env`, `.venv/`, credentials, API keys | Security risk |
| Copyrighted references | `references/articles/`, downloaded PDFs | Licence restrictions |
| Very large files (>50 MB) | Large datasets, binary assets | Use Git LFS instead |
| Build artefacts | `__pycache__/`, `node_modules/`, `*.pyc` | Reproducible from source |
| IDE/editor files | `.idea/`, `.vscode/`, `*.swp` | User-specific |

**Do NOT automatically ignore:**

- Output/results files (often small, valuable for reproducibility)
- Generated reports or analyses
- Configuration files (unless they contain secrets)
- Data files under a few MB

When uncertain, check the file size first. Small data files (<10 MB) are
generally fine to track directly.

### Pre-Commit Checklist

- [ ] Linting passed
- [ ] UK spelling throughout
- [ ] Acronyms expanded
- [ ] Comments added
- [ ] No secrets in code
- [ ] Commit message follows format
