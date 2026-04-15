---
name: notebook-creator
description: Generate valid Fieldmark notebook JSON files from natural language descriptions, field manuals, or specifications. Supports validation rules, conditional logic, and parent-child relationships.
---

# Fieldmark Notebook Creator

## When to Use This Skill

Activate when users request creation of Fieldmark notebooks, data collection forms, survey templates, or field data capture forms in JSON format.

**Trigger phrases:**
- "Create a Fieldmark notebook for..."
- "Generate a notebook JSON for..."
- "Build a data collection form that..."
- "Convert this field manual to a notebook..."

## Core Workflow

When this skill activates, follow these steps:

### 1. Understand Requirements

Accept input in multiple formats:
- **Natural conversation**: "I need a site survey with location, photos, and condition assessment"
- **Document-based**: User provides field manual, specification, or requirements document
- **Structured request**: User provides explicit field list with types

Extract these key details:
- Notebook purpose/name
- Required data fields (what information to collect)
- Field types (text, numbers, dates, selections, photos, GPS, etc.)
- Validation requirements (required fields, ranges, patterns)
- Conditional logic (show/hide fields based on other values)
- Relationships (parent-child record structures)

Ask clarifying questions only if critical information is missing. Infer sensible defaults when possible.

### 2. Read Fieldmark Documentation

**CRITICAL**: Always read the relevant sections of the Fieldmark reference documentation before generating JSON.

**Primary Reference**: `/home/shawn/Code/fieldmark-docs-staging/production/reference.md`

Read these sections as needed:
1. **Notebook Format Guide** - Overall structure and required properties
2. **Editor Component Mapping** - Map user requirements to Fieldmark components
3. **Component-specific documentation** - Detailed configuration for each field type
4. **Validation patterns** - ValidationSchema format and common rules
5. **Common errors and gotchas** - Critical requirements and error prevention

Use grep to find specific sections efficiently:
```bash
# Find component mapping
grep -A 50 "Editor Component Mapping" /path/to/reference.md

# Find specific component details
grep -A 30 "ComponentName" /path/to/reference.md

# Find validation patterns
grep -A 20 "validationSchema" /path/to/reference.md
```

### 3. Map Fields to Components

Based on the documentation read in step 2, map each user requirement to the appropriate Fieldmark component.

**Common mappings** (verify against reference.md):
- Short text → FAIMSTextField
- Long text → MultipleTextField (TextField with multiline)
- Single choice → Select
- Multiple choices → MultiSelect
- Yes/No → Checkbox
- Date → DatePicker
- Date/time auto-capture → DateTimeNow
- GPS location → TakePoint
- Photos → TakePhoto
- Numbers/measurements → NumberField
- Ratings (0-100) → TextField with InputProps.type="number"
- **Record ID (REQUIRED)** → TemplatedStringField

**CRITICAL**: Every notebook MUST include a TemplatedStringField for HRID (Human-Readable ID), or records will display as cryptic UUIDs.

### 4. Generate Valid JSON Structure

Follow the Fieldmark notebook structure from reference.md:

```json
{
  "metadata": {
    "notebook_version": "1.0",
    "schema_version": "1.0",
    "name": "Notebook Name",
    "accesses": ["admin", "moderator", "team"],
    "ispublic": false,
    "isrequest": false,
    "lead_institution": "Organisation Name",
    "project_lead": "Lead Name",
    "project_status": "New",
    "pre_description": "Description of notebook purpose"
  },
  "ui-specification": {
    "fields": { /* field definitions */ },
    "fviews": { /* view groupings */ },
    "viewsets": { /* form configuration */ },
    "visible_types": [ /* enabled forms */ ]
  }
}
```

**Key requirements** (verify details in reference.md):
- Every field must have: component-namespace, component-name, type-returned, component-parameters, validationSchema, initialValue, meta
- Field `name` in component-parameters MUST match field ID
- ValidationSchema uses array-of-arrays format: `[["yup.string"]]`
- fviews must be separate section (NOT nested in viewsets)
- Viewsets reference fviews as string arrays
- Include TemplatedStringField and reference it in viewsets.hridField

### 5. Organise Fields into Sections

Group related fields into logical fviews (3-8 fields per section):

**Common sections:**
- Identification (record ID, name, type)
- Location & Documentation (GPS, date, photos)
- Measurements (numeric fields)
- Assessment (condition, status, ratings)
- Notes & Observations (text areas)

Place the HRID field (TemplatedStringField) in the first fview.

### 6. Validate Before Writing

Before writing the file, verify against the validation checklist in reference.md:

**Critical checks:**
- [ ] Field names match between field ID and component-parameters.name
- [ ] TemplatedStringField exists and is referenced in viewsets.hridField
- [ ] ValidationSchema in array-of-arrays format (not strings)
- [ ] All required metadata fields present
- [ ] fviews section exists separately (not nested)
- [ ] Viewsets reference fviews as string arrays
- [ ] InitialValue types match field types

### 7. Write to File

Ask user: "Where should I save this notebook JSON?"

**Default suggestion**: `/home/shawn/Code/fieldmark-docs-staging/production/outputs/example-notebooks/[notebook-name].json`

Write the file with:
- 2-space indentation
- Proper JSON formatting
- Kebab-case field IDs (e.g., `site-name`)

Confirm success with summary:
- Number of fields created
- Sections organised
- Key features included
- File location

## Advanced Features

### Validation Rules

Read validation patterns from reference.md. Common patterns:
- Required fields: `[["yup.string"], ["yup.required", "Error message"]]`
- Number ranges: `[["yup.number"], ["yup.min", 0], ["yup.max", 100]]`
- Regex patterns: `[["yup.string"], ["yup.matches", "pattern", "Error"]]`

### Conditional Logic

Use is-logic to show/hide fields:
```json
"field-name": {
  "is-logic": {
    "if": "other-field",
    "==": "value"
  }
}
```

### Parent-Child Relationships

Use RelatedRecordSelector for linking records:
- Set `related_type` to viewset name
- Set `relation_type` to "faims-core::Child" or "faims-core::Parent"
- Set `multiple` to true/false

Details in reference.md under RelatedRecordSelector.

## Examples Reference

Review example notebooks for patterns:
- **Human-made**: `/home/shawn/Code/fieldmark-docs-staging/archive/example-notebooks/`
- **AI-generated**: `/home/shawn/Code/fieldmark-docs-staging/production/outputs/example-notebooks/`

Read examples when:
- User requests similar functionality
- Implementing complex features (relationships, conditionals)
- Validating generated structure

## Common Use Cases

Generate notebooks for:
- Site surveys (location, photos, assessments)
- Archaeological recording (contexts, artefacts, stratigraphy)
- Species observations (identification, counts, behaviour, habitat)
- Condition assessments (scores, defects, urgency)
- Equipment inspections (pass/fail, checklists, corrective actions)

## Error Prevention

**Most common errors** (details in reference.md):

1. **Field name mismatch**: Name in component-parameters doesn't match field ID
2. **Missing HRID field**: No TemplatedStringField for readable record IDs
3. **Wrong validationSchema format**: String instead of array-of-arrays
4. **Nested fviews**: Views nested in viewsets instead of separate section
5. **Wrong initialValue type**: Type mismatch (e.g., string for number field)

Always read the "Common Errors" section in reference.md before writing JSON.

## Default Values

Use these defaults unless user specifies otherwise:
- `accesses`: `["admin", "moderator", "team"]`
- `ispublic`: `false`
- `isrequest`: `false`
- `project_status`: `"New"`
- `publishButtonBehaviour`: `"always"`

## Remember

- **Single source of truth**: reference.md contains all accurate, up-to-date information
- **Read before generating**: Always consult reference.md for component details
- **Validate before writing**: Check against validation checklist
- **HRID is mandatory**: Every notebook needs a TemplatedStringField
- **Progressive disclosure**: Read specific sections as needed, not everything at once
