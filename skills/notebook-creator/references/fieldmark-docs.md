# Fieldmark Documentation Reference

## Source of Truth

Fieldmark documentation uses the [llms.txt standard](https://llmstxt.org/) for progressive disclosure:

- **Navigation index**: `/home/shawn/Code/fieldmark-docs-staging/llms.txt` (~8K tokens)
- **Full corpus**: `/home/shawn/Code/fieldmark-docs-staging/llms-full.txt` (~42K lines)
- **Source files**: `/home/shawn/Code/fieldmark-docs-staging/production/inputs/` subdirectories

## How to Use This Reference

When generating Fieldmark notebooks, load `llms.txt` first to identify relevant source files, then fetch only those files.

### Key Files for Notebook Generation

| Task | File to load |
|------|-------------|
| Component mappings (Designer → JSON) | `production/inputs/references/editor-component-mapping.md` |
| Notebook JSON structure | `production/inputs/references/notebook-format-guide.md` |
| Complete working examples | `production/inputs/references/notebook-templates.md` |
| Field type details | `production/inputs/field-categories/*.md` (see llms.txt for specific files) |
| Validation rules | Search for "validationSchema" in `editor-component-mapping.md` |
| Form layout (viewsets, fviews) | `production/inputs/patterns/form-structure-guide.md` |
| Conditional logic | `production/inputs/patterns/dynamic-forms-guide.md` |
| Common patterns and recipes | `production/inputs/patterns/cookbook.md` |

### Workflow for Reading Documentation

1. **Start broad**: Load `notebook-format-guide.md` for overall JSON structure
2. **Get mappings**: Load `editor-component-mapping.md` for Designer → JSON lookup
3. **Get specific**: Load the relevant field-category file for detailed field configuration
4. **Check examples**: Load `notebook-templates.md` for pattern validation
5. **Verify**: Use the validation checklist from `notebook-format-guide.md` before writing JSON

### Example Notebooks

**Location**: `/home/shawn/Code/fieldmark-docs-staging/archive/example-notebooks/`
**Contains**: Human-made and AI-generated example notebooks for pattern reference.

## Note on Sync

The source files in `production/inputs/` are the authoritative documentation. When the Fieldmark software is updated, these files are updated and `llms-full.txt` is rebuilt automatically via `npm run build`.
