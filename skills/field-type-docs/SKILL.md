---
name: field-type-docs
description: Generate modular "lego brick" documentation for Fieldmark field types. Produces design docs (Notebook Editor configuration), collect docs (data collection usage), shared docs, Playwright screenshot specs, and practical fieldwork tips. This skill should be used when creating, updating, or reviewing field type documentation for the fieldmark-docs-staging repository.
---

# Fieldmark Field Type Documentation Generator

## When to Use This Skill

Activate when working on field type documentation in the `fieldmark-docs-staging`
repository. This includes:

- Creating new field type design or collect documents
- Updating existing field type documents
- Adding Playwright screenshot test cases for field types
- Reviewing field type documentation for consistency
- Creating or updating shared documentation (field toolbar, identity, options)

**Trigger phrases:**

- "Create field type docs for..."
- "Document the Select field"
- "Add field type documentation for..."
- `/field-type-doc <field-name>`

## Architecture Overview

### Document Types

Field type documentation uses a modular "lego brick" architecture with four
document categories:

| Category | Location | Purpose |
|----------|----------|---------|
| **Design docs** | `field-types/design/{slug}.md` | How to add and configure in the Notebook Editor |
| **Collect docs** | `field-types/collect/{slug}.md` | How the field works when collecting data |
| **Shared docs** | `field-types/design/shared/` | Common features documented once, linked from field docs |
| **Index** | `field-types/README.md` | Catalogue of all field types with status |

All paths are relative to `production/outputs/human-readable/`.

### Shared Documents

These cover features common to most or all field types. Each field-type doc
links to these rather than repeating the content. Field-type docs may include
brief *tips* about how shared features apply to that specific field, but must
not duplicate the mechanics.

| Shared Doc | Covers | Screenshot |
|------------|--------|------------|
| `adding-a-field.md` | The ADD A FIELD modal: clicking the button, navigating tabs (ALL, TEXT, NUMBERS, DATE & TIME, MEDIA, LOCATION, CHOICE, RELATIONSHIP, DISPLAY), scrolling with arrow buttons, selecting a field type | `shared-01-add-field-modal.png` |
| `field-toolbar.md` | The icon toolbar at top-right of each expanded field: delete, move to section, reorder (up/down arrows), duplicate, copy field ID, hide/show, and the overflow menu | `shared-02-field-toolbar.png` |
| `field-identity.md` | Label, Helper Text, and Field ID — what each setting does and how they appear in data collection | `shared-03-field-identity.png` |
| `field-options.md` | The options panel at the bottom of each field: Required, Annotation (with Annotation Label), Uncertainty, ADD CONDITION, Copy value to new records, Display in child records | `shared-04-field-options.png` |

### Screenshot Conventions

**Directory structure:**

```text
production/inputs/screenshots/
  field-types-design/
    final/              # Design doc screenshots (Notebook Editor)
  field-types-collect/
    final/              # Collect doc screenshots (data collection app)
```

**Naming pattern:** `{slug}-{nn}-{description}.png`

- `{slug}` — lowercase hyphenated field name matching the doc filename
- `{nn}` — two-digit sequence number
- `{description}` — brief descriptor

**Standard screenshots per field type:**

| # | Design Doc | Collect Doc |
|---|------------|-------------|
| 01 | `{slug}-01-add-field.png` — ADD A FIELD tab showing this field's card | `{slug}-01-empty.png` — empty field in collection form |
| 02 | `{slug}-02-configured.png` — the field "zone": from this field's grey header bar to the next field's grey header bar | `{slug}-02-filled.png` — field with data entered |
| 03 | `{slug}-03-{specific}.png` — (rare) second zone screenshot for fields too tall for one viewport | Optional: validation states, special interactions |

**Screenshot sequence:**

- **01** (always): ADD A FIELD dialog showing this field's card.
- **02** (usually sufficient): the entire field "zone" in the
  Editor — from the field's grey header bar at the top to the
  next field's grey header bar at the bottom. Most fields fit
  in a single screenshot. The shared field options panel is
  visible within this zone, so no separate screenshot is needed.
- **03** (rare): only when the field zone is too tall for one
  viewport (e.g., Select with 7+ options). Split using the
  anchoring rules below.
- There is no 04 — shared field options are visible within the
  zone screenshot(s), not captured separately.

**Screenshot composition / anchoring rules:**

The field "zone" is everything from the field's grey header bar
to the next field's grey header bar.

- **02-configured**: anchor with the field's grey header bar at
  the top of the viewport (~20 px offset above the header).
- **If the entire zone fits in one viewport**: use a single 02
  screenshot. This is the common case.
- **If it does NOT fit** (rare — e.g., Select with many options):
  the first screenshot (02) anchors with the field header at the
  top; the second screenshot (03) anchors on the **next** field's
  `.MuiAccordionSummary-content` with offset ≈ 780 (viewport
  height minus dialog chrome minus margin), so the next field's
  grey header bar is just visible at the bottom edge.
- Together, the screenshots must cover the complete field zone
  with no content cut off or gaps.

**Shared doc screenshots** use the `shared-` prefix and live in `field-types-design/final/`.

## Core Workflow

### Step 1: Read Source Material

Before generating any document, read the relevant source files to extract
accurate content. Never generate field type documentation from general knowledge
alone.

**Primary sources** (read the section for the target field type):

```text
production/inputs/field-categories/
  text-fields-v05.md              # FAIMSTextField, MultipleTextField, Email,
                                  # TemplatedStringField, QRCodeFormField,
                                  # AddressField, RichText
  select-choice-fields-v05.md     # Select, MultiSelect, AdvancedSelect,
                                  # Checkbox, RadioGroup
  number-fields-v05.md            # NumberField, ControlledNumber,
                                  # BasicAutoIncrementer
  datetime-fields-v05.md          # DateTimeNow, DateTimePicker, DatePicker,
                                  # MonthPicker
  location-fields-v05.md          # TakePoint, MapFormField
  media-fields-v05.md             # TakePhoto, FileUploader
  relationship-field-v05.md       # RelatedRecordSelector
  display-field-v05.md            # RichText
```

**Secondary sources:**

```text
production/inputs/patterns/field-selection-guide.md   # Kinetic fieldwork advice
production/inputs/references/editor-component-mapping.md  # Designer UI names
```

**Key sections to extract from each field's source material:**

- Purpose and use cases (→ "What This Field Does")
- Designer UI name and tab location (→ "Adding the Field")
- Configuration options specific to this field (→ "Configuring the Field")
- Known issues and platform notes (→ "Tips")
- "When to use" guidance and decision criteria (→ "Tips")

### Step 2: Check the Field Registry

Consult `references/field-registry.md` in this skill's directory for:
- The correct Designer UI name (what users see in the ADD A FIELD modal)
- Which tab the field appears under (CHOICE, TEXT, etc.)
- The component name and namespace (for technical accuracy)
- The document slug (filename)
- Any status labels (beta, deprecated, mobile-only)

### Step 3: Generate the Design Doc

Use the design doc template below. Key principles:

- **Beginner to intermediate audience** — assume users can navigate a web app
  but have never used the Notebook Editor before
- **Practical, not exhaustive** — cover what users need to configure the field,
  not every technical detail
- **Link to shared docs** — do not repeat shared feature mechanics
- **Include 2-3 targeted tips** — drawn from source material, focused on
  helping users choose and configure wisely
- **UK/Australian English** throughout

#### Design Doc Template

```markdown
# {Designer UI Name}

*How to add and configure a {Designer UI Name} field in the Notebook Editor.*

---

## What This Field Does

{2-3 sentences: purpose, what data it captures, typical use cases.
Use concrete examples from archaeology, ecology, or field science.}

## Adding the Field

To add this field, open the [ADD A FIELD dialog](shared/adding-a-field.md),
navigate to the **{TAB NAME}** tab, and click **{Designer UI Name}**.

![Adding a {name} field](../../../../inputs/screenshots/field-types-design/final/{slug}-01-add-field.png)

## Configuring the Field

Click the field's **grey header bar** to expand it and see its settings.
For an overview of the settings shared by all fields — including Label,
Helper Text, Field ID, and the field toolbar — see
[Field Identity](shared/field-identity.md) and
[Field Toolbar](shared/field-toolbar.md).

![{name} configuration](../../../../inputs/screenshots/field-types-design/final/{slug}-02-configured.png)

Give the field a meaningful Label, review the auto-populated
Field ID, and add any desired Helper Text.

### {Field-Type Name}-Specific Settings

{Table or description of settings UNIQUE to this field type.
For example, for Select: the options list, Markdown in options, reordering.
For ControlledNumber: min, max, step. Omit settings covered by shared docs.}

| Setting | What It Does |
|---------|-------------|
| **{Setting}** | {Description} |

{If the field has interactive settings (e.g., options list, hierarchy
editor), include a screenshot showing those settings in use:}

![{name} {specific settings}](../../../../inputs/screenshots/field-types-design/final/{slug}-03-{specific}.png)

{For fields with interactive settings, add procedural instructions.
Use bold lead-in phrases for each action:}

**Managing {items}:**

- **To add {an item}:** {How to add.}
- **To edit {an item}:** {How to edit.}
- **To reorder {items}:** {How to reorder.}
- **To delete {an item}:** {How to delete.}

{Include any important notes about data behaviour — e.g., "The display
label and stored value are always the same" for Select fields.}

### Shared Field Options

Configure any of the shared field options as needed.

For settings shared across all field types — including Required,
Annotation, Uncertainty, Conditions, Copy value to new records,
and Display in child records — see
[Field Options](shared/field-options.md).

## Tips

{2-3 bullet points of practical advice specific to THIS field type.
Draw from field-selection-guide.md and the field's source documentation.
Focus on helping users choose wisely and avoid common mistakes.
Do NOT repeat shared feature mechanics.}

- {Tip about when to use this field vs alternatives}
- {Tip about a common configuration choice or gotcha}
- {Optional: tip about fieldwork practicalities}
```

### Step 4: Generate the Collect Doc

Use the collect doc template below. The audience is **data collectors** —
people using the app in the field, not notebook designers.

#### Collect Doc Template

```markdown
# {Designer UI Name}

*How the {Designer UI Name} field works when you are collecting data.*

---

## What You Will See

{1-2 sentences describing the field's appearance in the data collection app.}

![{name} in the data collection app](../../../../inputs/screenshots/field-types-collect/final/{slug}-01-empty.png)

## How to Use It

{Numbered steps for interacting with the field. Keep it brief and practical.}

1. {First step}
2. {Second step}

![{name} with data entered](../../../../inputs/screenshots/field-types-collect/final/{slug}-02-filled.png)

## What Gets Saved

{1-2 sentences in plain language: what data is recorded and in what format.
Avoid technical jargon — "saves your choice as text" not "returns
faims-core::String".}

## Tips

{1-3 practical tips for data collectors using this field in the field.}
```

### Step 5: Add Playwright Screenshot Specs

Add test cases to the existing spec files following the established pattern.

**Design screenshots** → `production/tooling/screenshots/guides/field-types-design.spec.ts`
**Collect screenshots** → `production/tooling/screenshots/guides/field-types-collect.spec.ts`

Each field type needs a single `test.describe` block containing one
consolidated test that navigates once and captures all screenshots
sequentially. This matches the actual implementation pattern.

**Standard test structure for design screenshots:**

```typescript
test.describe('{Designer UI Name}', () => {
  // Simple fields (no field-specific settings): 2 screenshots
  test('01–02: add field, configured', async ({ page }) => {
    // 01 — ADD A FIELD dialog
    // Click ADD A FIELD button
    // Navigate to {TAB} tab (scroll with › button if needed)
    // Screenshot the dialog showing this field's card

    // 02 — configured field (field zone)
    // Close dialog, navigate to section via MuiStepper
    // Expand the field (click grey header bar)
    // Use screenshotInDialog() with ~20px offset to anchor
    //   the field's header bar at the top of the viewport
    // Screenshot the complete field zone
  });

  // Complex fields (with field-specific settings): 3 screenshots
  test('01–03: add field, configured, {specific}', async ({ page }) => {
    // 01 — ADD A FIELD dialog (same as above)

    // 02 — configured field (top of zone)
    // screenshotInDialog() with ~20px offset above the header bar

    // 03 — field-specific settings (bottom of zone)
    // screenshotInDialog() anchored on the NEXT field's
    //   .MuiAccordionSummary-content with offset ≈ 780
    //   (viewport height minus dialog chrome minus margin)
    // The next field's grey header bar should be just visible
    //   at the bottom edge
  });
});
```

**Playwright tips:**

- Use `.MuiStepper-root > .MuiStep-root` and `.nth(index)` to navigate
  sections — `text=Feature` may match sidebar elements instead.
- Anchor scroll positions to specific text content (e.g., first option
  name) rather than generic labels like "Markdown syntax" which may
  appear at the same height as the identity section.
- Use `screenshotInDialog()` as the standard helper for all field
  configuration screenshots. This helper directly adjusts the MUI
  Dialog's internal scroll container (`scrollTop`) rather than using
  `window.scrollTo()`, which does not work with MUI Dialog components.
- For multi-screenshot fields, the bottom-anchoring technique uses the
  **next** field's `.MuiAccordionSummary-content` as the anchor element
  with an offset of ≈ 780 px, placing the next field's grey header bar
  at the bottom edge of the viewport.

### Step 6: Adversarial QA Pass

After writing the documentation and capturing screenshots, perform a
rigorous quality audit **before** committing. This step exists because
LLM-generated documentation has a systematic tendency to "satisfice" — to
produce text that *reads* plausibly but contains factual errors, omissions,
and fabricated details that a human reviewer would catch. The purpose of
this step is to catch those errors before a human ever sees the output.

**This step is mandatory, not optional.** Do not skip it. Do not combine
it with the writing step. Perform it as a distinct pass after the
documentation is complete.

#### Anti-satisficing rules

These rules exist to counteract specific failure modes observed in
LLM-generated documentation:

1. **Re-read every screenshot fresh.** Do not rely on memory from when you
   wrote the doc. Open each screenshot again using the Read tool and
   examine it as if seeing it for the first time. Memory-based verification
   is the primary cause of satisficing — you "remember" what you think the
   screenshot shows, and that memory confirms your text, even when both
   are wrong.

2. **Never declare a claim "correct" without visible evidence.** If a
   claim cannot be verified from the screenshot or a cross-reference
   source, mark it "assumed — not verifiable from screenshot" rather than
   "correct". The human reviewer needs to know what you checked and what
   you didn't.

3. **Count elements.** If the screenshot shows 7 toolbar icons, the doc
   must document exactly 7. If the screenshot shows 9 tabs, the doc must
   list exactly 9. Count the elements in the screenshot, count the items
   in the doc, and compare the numbers. Mismatched counts reveal omissions
   and fabrications.

4. **Verify in both directions.** Check screenshot → doc (is every visible
   element documented?) AND doc → screenshot (does every doc claim have
   visible evidence?). One-directional checking misses omissions in one
   direction and fabrications in the other.

5. **Check exact text, not semantic equivalence.** If the UI says "Copy
   value to new records" (sentence case) and the doc heading says "Copy
   Value to New Records" (title case), that is an error. If the UI card
   says "Auto Incrementing Field" and the doc says "Unique ID", that is
   an error. Exact string matching, not "close enough".

6. **Cross-reference the field registry.** For every field name, tab name,
   and Designer UI name in the doc, verify it against
   `references/field-registry.md`. Where the registry and the live UI
   disagree, note the discrepancy and prefer the live UI (the screenshot)
   for user-facing docs.

7. **Distrust your own generated text the most.** Text you wrote from
   source material is more likely to contain errors than text you copied
   from the UI. Tab contents tables, toolbar icon descriptions, and
   behavioural claims (e.g., "the Field ID auto-lowercases") are the
   highest-risk categories.

8. **Verify screenshot consistency and coverage.** For each field
   type: (a) use the Read tool to visually examine every
   screenshot — do not rely on memory of what they contain;
   (b) confirm the 02-configured screenshot shows the field's
   grey header bar near the top of the viewport, consistently
   framed with other field types; (c) confirm the screenshot
   set covers the complete field "zone" — from the field's grey
   header bar to the next field's grey header bar — with no
   content cut off; (d) if the zone spans multiple screenshots,
   verify the final screenshot shows the next field's header bar
   at its bottom edge; (e) no separate 04-settings screenshot
   exists — shared field options must be visible within the zone
   screenshot(s).

#### What to verify

For each document, verify every claim against the screenshot evidence:

| Category | Check | Common Errors |
|----------|-------|---------------|
| **UI element names** | Exact text match against screenshot/DOM | Wrong capitalisation, registry name vs card label, "ADD A FIELD" (button) vs "Add a field" (dialog title) |
| **Element counts** | Count items in screenshot, match to doc | Missing fields from tab tables, missing toolbar icons, missing options |
| **Layout descriptions** | Verify spatial claims against screenshot | "top-right corner" when icons are mid-row; "below" when element is beside |
| **Behavioural claims** | Verify against screenshot evidence or source material | "auto-lowercases" when capitalisation is preserved; "pre-populates" claims |
| **Completeness** | Every visible UI element accounted for | Badges, preview text, section dividers, buttons (especially CANCEL) |
| **Alt text** | Matches what the screenshot actually shows | Generic alt text that doesn't match the specific screenshot content |
| **Cross-references** | Links resolve; shared doc references are accurate | Broken relative links, wrong shared doc referenced |
| **Style guide** | Active voice, bold verbs, correct UI terminology | "click the button" not "the button should be clicked"; "card" not "tile" |
| **Screenshot framing** | Header bar at top of 02, complete zone coverage across all shots, next-field header visible at bottom of final shot | Missing content, inconsistent framing, redundant shared-options screenshot |

#### Required output format

Produce a tabulated audit for each document. The table forces systematic
checking and gives the human reviewer a clear record of what was verified:

```markdown
## Audit: {filename} vs {screenshot}

| # | Doc Claim (line) | Screenshot Evidence | Verdict |
|---|------------------|--------------------|---------|
| 1 | {specific claim} | {what screenshot shows} | Correct / ERROR / OMISSION |
```

Every row must have a verdict. Every verdict must cite evidence. "Looks
fine" is not a verdict.

After the table, provide:

- **Error count**: X errors, Y omissions, Z inconsistencies
- **Fixes applied**: What you changed and why
- **Remaining limitations**: What couldn't be verified from available
  screenshots

#### Known high-risk patterns

These specific error patterns have been observed in prior QA passes. Check
for them explicitly:

- **Fabricated tab contents**: Listing field types under tabs based on
  guesswork rather than the field registry or live UI. The ALL tab shows
  all fields; per-tab contents require the registry or clicking each tab.
- **Registry name vs card label mismatch**: The field registry's "Designer
  UI Name" column sometimes differs from the actual card label in the ADD
  A FIELD modal (e.g., registry says "Unique ID", card says "Auto
  Incrementing Field"). User-facing docs must use the **card label**.
- **Behavioural claims without evidence**: Statements about what happens
  when you interact with a UI element (e.g., "auto-lowercases",
  "pre-populates", "displays a badge") that were inferred rather than
  observed. Verify against screenshots or flag as unverifiable.
- **Missing visible elements**: Buttons (CANCEL), badges (Required,
  type badges), preview text (Helper Text in green italic), and
  section-specific settings (Speech-to-Text) that are visible in the
  screenshot but not mentioned in the doc.
- **Heading case vs UI case**: Doc headings using title case for options
  that appear in sentence case in the UI.

### Step 7: Update the Index

After creating a new field type's documents, update the index at
`production/outputs/human-readable/field-types/README.md`:

- Add the field to the appropriate table row
- Link to both design and collect docs
- Add status labels if applicable (Beta, Deprecated, Mobile Only)

## Content Guidelines

### Tone and Depth

- **Audience**: Beginner to intermediate users designing notebooks for
  fieldwork
- **Tone**: Practical and encouraging, like a colleague showing you the ropes
- **Depth**: Cover what users need to know, not everything there is to know
- **Examples**: Use concrete scenarios from archaeology, ecology, geology,
  or heritage recording — the user base is field scientists

### Writing Style

- **Concrete over abstract.** Show UI states paired with data
  values — "checked (true) or unchecked (false)" rather than
  "binary true/false toggle". Non-technical audiences understand
  concrete demonstrations faster than abstract definitions.
- **Line wrap to ~80 characters.** Wrap prose lines for readable
  diffs and consistent formatting. Do not exceed 100 characters
  (project maximum).
- **"e.g." for illustrative lists.** When listing examples
  parenthetically, prefix with "e.g." to signal the list is not
  exhaustive: "(e.g., Select Field, Select Multiple)".
- **Lowercase for descriptive terms.** Use "shared field options"
  (descriptive phrase) in body text, not "Shared Field Options"
  (proper noun). Headings remain capitalised per heading rules.
- **Match Designer UI card names exactly.** In tips and cross-
  references, always use the exact card text from the ADD A FIELD
  modal. Do not substitute technical or informal names. Examples:
  - The single-choice field: card text is "Select one
    option" — do NOT use "radio button group", "radio button
    array", or "Radio Buttons" (the term "radio button" only
    appears in the helper text, not on the card itself)
  - The hierarchical selection field: card text is "Select Field
    (Hierarchical)" — do NOT use "Hierarchical Select"
  Consult the field registry when uncertain.
- **"review the auto-populated Field ID"** — not "auto-populate
  the Field ID". The system auto-populates; the user reviews.

### Tips: What to Include

Tips should help users make good decisions. Draw from the field selection
guide and source documentation, but keep them brief (1-2 sentences each).

**Good tip examples:**

- "Select is ideal for lists of 8–20 options. For shorter lists (2–7),
  consider 'Select one option' so all choices are visible at a glance.
  For very long or structured lists, use Select Field (Hierarchical)."
- "Include a `-- None --` option if users need to clear a selection —
  there is no built-in deselect button."
- "Enable Annotation for fields where collectors might need to qualify
  their choice, such as noting 'tentative identification' or
  'poor visibility'."
- "Mark fields as Required only when the data is genuinely essential.
  Over-using Required creates friction and slows recording in the field."

**Bad tip examples (too deep, too generic, or duplicates shared docs):**

- ❌ "The Select field returns a faims-core::String value..." (too technical)
- ❌ "Click the Required checkbox to make this field required." (shared doc)
- ❌ "Always save your work." (too generic)

### Tips: Source Material

Consult `references/tips-library.md` in this skill's directory for
pre-extracted practical advice organised by field type. This library draws
from the field selection guide's kinetic fieldwork principles:

- Minimise recording friction
- Design for environmental extremes (bright sun, rain, cold fingers)
- Optimise for common cases
- Respect device constraints on mobile

### Status Labels

Some field types need prominent status labels:

| Label | Fields | Treatment |
|-------|--------|-----------|
| **Deprecated** | RadioGroup | Warning banner at top of doc, advise using Select instead |
| **Beta** | AddressField, AdvancedSelect | Note in "What This Field Does", mention limitations |
| **Mobile Only** | QRCodeFormField | Note in both design and collect docs |

### What NOT to Include

- JSON configuration details (this is editor documentation, not developer docs)
- Component namespaces or internal names
- Validation schema syntax
- Formik/React implementation details
- Deep platform-specific behaviour tables

## File Naming Convention

All filenames use the Designer UI display name converted to lowercase with
hyphens. Matching names across `design/` and `collect/` directories.

Consult `references/field-registry.md` for the canonical slug for each field.

## Conversion Pipeline

After creating documents, they can be converted to MyST format for the
upstream FAIMS3 docs:

```bash
bash production/tooling/scripts/convert-for-sphinx.sh
```

The conversion script handles:
- Image path transformation to `{screenshot}` directives
- Variable substitutions (Fieldmark → `{{FAIMS}}`, notebook → `{{notebook}}`, etc.)
- Subdirectory structure preservation

## Demo Notebook

The `fieldmark-field-types-demo` notebook on the staging server contains all
24 field types with realistic archaeological data. Use it for both design
and collect screenshots.

- **Project ID**: `1770721372059-field-types-demo`
- **Dashboard URL**: `https://web.test.fieldmark.app/projects/1770721372059-field-types-demo`
- **App URL**: `https://app.test.fieldmark.app` (for collect screenshots)

## Quick Reference: Batch Priority

When generating docs for multiple field types, follow this priority order:

**Batch 1 — Core fields** (most commonly used):
FAIMSTextField, MultipleTextField, Select, Checkbox, Email, MultiSelect,
NumberField

**Batch 2 — Date/time and specialised**:
DateTimeNow, DatePicker, MonthPicker, DateTimePicker, ControlledNumber,
TemplatedStringField

**Batch 3 — Media, location, and structured**:
TakePhoto, FileUploader, TakePoint, MapFormField, RelatedRecordSelector,
RichText, BasicAutoIncrementer, RadioGroup (deprecated)

**Batch 4 — Beta and edge cases**:
AddressField (beta), AdvancedSelect (beta), QRCodeFormField (mobile-only)
