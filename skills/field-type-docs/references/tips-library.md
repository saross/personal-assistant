# Tips Library — Practical Fieldwork Advice by Field Type

Pre-extracted tips from the field selection guide and field category
documentation. Use 2-3 of these per field type document, selected for
relevance to the specific field. Adapt the wording to fit the document
context; do not copy verbatim.

## Guiding Principles (from field-selection-guide.md)

These five principles underpin all tips. Reference them when writing
advice but do not list them directly in field type docs:

1. **Minimise recording friction** — automate everything the system can know
2. **Design for environmental extremes** — bright sunlight, rain, cold fingers
3. **Prefer structure over free text** — controlled vocabularies where feasible
4. **Design for the data lifecycle** — from collection through analysis
5. **Progressive disclosure** — hide complexity until needed via conditions

---

## Text Fields

### FAIMS Text Field

- Best for short, predictable entries under ~100 characters (site codes,
  brief descriptions, single-line observations). For longer text, use
  Multiline Text Field instead.
- When you find yourself typing the same values repeatedly, consider
  whether a Select field with a controlled vocabulary would be more
  efficient and produce cleaner data.
- Works well with "Copy value to new records" for fields that rarely
  change between entries (e.g., recorder initials, weather conditions).

### Multiline Text Field

- Designed for extended narrative: context descriptions, detailed
  observations, condition assessments. Use when entries commonly exceed
  a sentence or two.
- On mobile devices, the touch keyboard can obscure the text area. Keep
  sections with multiline fields towards the end of a form so users
  can review earlier entries before writing descriptions.
- Consider enabling Annotation for multiline fields where the main text
  is structured but might need a qualifying note (e.g., "description
  based on surface observation only").

### Email Field

- Provides email-specific keyboard layout on mobile (with @ symbol
  prominently placed), making entry faster and less error-prone than a
  plain text field.
- Useful for contact details that need to be actionable — project
  collaborators, museum liaisons, local authority contacts.
- Validation is format-only (checks for valid email structure); it does
  not verify the address exists.

### Templated String (Unique ID)

- Essential for every form — without a Templated String for human-readable
  IDs, records get opaque UUIDs like "rec-5f8a9b3c" that are impossible
  to reference in conversation or field notes.
- Combine meaningful components: site code + year + type + sequence
  (e.g., "PPAP-2026-CTX-045"). This makes records self-describing.
- Templated Strings are read-only for data collectors — they see the
  generated ID but cannot edit it, preventing accidental corruption.

### QR / Barcode Scanner

- Mobile only — this field will not work in the desktop web app. Note
  this prominently if the notebook will be used on both platforms.
- Excellent for linking physical artefacts (bagged finds, sample tubes,
  equipment) to digital records via pre-printed barcode labels.
- The scanner accepts multiple barcode formats; test with your actual
  labels before deploying to the field.

### Address

- Beta feature — may have rough edges. Test thoroughly before relying
  on it for critical workflows.
- Provides structured address components (street, city, postcode, etc.)
  rather than a single text blob, which is better for downstream
  analysis and correspondence.
- Auto-complete availability varies by platform and region; do not
  assume it will always suggest addresses.

---

## Selection / Choice Fields

### Select Field (Dropdown)

- Best for single-selection lists of 8–20 options. The dropdown conserves
  screen space while handling moderate lists well.
- For shorter lists (2–7 items), consider Radio Buttons ("Select one
  option") so all choices are visible without opening a dropdown — faster
  for experienced collectors. For very long or structured lists (>20),
  use Hierarchical Select.
- Include a blank or "-- None --" option if collectors need to clear a
  selection — there is no built-in deselect button.
- The Designer enforces that value equals label, so what users see is
  exactly what appears in exported data. No hidden codes.
- Use **Add "Other" Option** when your list is mostly controlled but
  collectors occasionally encounter unexpected values. The "Other"
  choice prompts them to type a custom value, keeping your data
  structured while allowing flexibility.
- Enable Annotation when collectors might need to qualify their choice
  (e.g., "tentative identification", "poor lighting conditions").

### Select Multiple (Multi-Select)

- Use when items are not mutually exclusive — multiple materials present,
  multiple features observed, multiple conditions noted simultaneously.
- For fewer than ~10 options, the expanded checklist mode shows all
  choices at once, which is faster than a dropdown. For longer lists,
  use the default dropdown mode.
- Configure exclusive options when certain choices invalidate others
  (e.g., selecting "None observed" should clear other selections).
- Use **Add "Other" Option** for controlled vocabularies that
  occasionally need ad-hoc entries. The "Other" choice prompts for a
  custom value alongside the structured selections.
- Data exports as arrays; plan for this in analysis workflows.

### Select one option (Radio Group) — DEPRECATED

- Deprecated due to critical bugs (deselection issues, no error display,
  accessibility failures). Use Select Field instead for all new notebooks.
- Historical advantage was that all options were visible simultaneously,
  making selection faster for short lists. Select Field with a small
  option list provides similar usability without the bugs.
- If migrating an existing notebook, note the field options before
  deleting the Radio Group, then recreate as a Select Field — there is
  no direct conversion.

### Checkbox

- The only boolean (true/false) field type in Fieldmark. Use for binary
  indicators: "Photographed?", "Sample collected?", "Recording complete?"
- Works well as a gateway for conditional fields — tick "Detailed
  measurements needed?" to reveal additional measurement fields. This
  keeps forms simple for routine entries while enabling depth when
  required.
- Known quirk: the label text is not clickable — users must tap the
  small checkbox icon itself. Mention this in training if deploying
  on mobile.

### Select Field (Hierarchical) — BETA

- Beta feature — works well on desktop but has layout issues on mobile
  (fixed 500px width causes horizontal scrolling on phones).
- Excellent for structured taxonomies: pottery typologies, geological
  classifications, vegetation communities. The tree navigation feels
  natural for inherently hierarchical data.
- Currently requires JSON editing for the hierarchy structure — the
  Designer does not yet provide a visual tree editor. Plan for this
  setup time.
- Performance degrades noticeably above ~100 tree nodes. For very large
  taxonomies, consider splitting into cascading Select fields instead.

---

## Number Fields

### Number Input

- The simpler of the two number fields — no minimum/maximum validation.
  Suitable when any numeric value is valid (arbitrary counts, reference
  numbers).
- For measurements with known valid ranges (pH 0-14, percentage 0-100,
  depth in cm), use Controlled Number instead — it prevents out-of-range
  entries at the point of collection.
- Enable Annotation for all measurement fields — collectors should be
  able to note the instrument used, measurement conditions, or
  estimation method.

### Controlled Number

- Enforces minimum and maximum values, catching data entry errors
  immediately rather than during post-processing. Set ranges based on
  what is physically plausible, not just what is expected.
- Supports "sticky" behaviour — the value persists across new records.
  Useful for environmental constants that rarely change during a
  recording session (e.g., weather station readings, soil moisture).
- Consider the step size: for integer counts use step=1; for
  measurements requiring one decimal place, use step=0.1.

### Unique ID (Auto-Incrementer)

- Generates sequential identifiers automatically (001, 002, 003...).
  Cannot be reset mid-project — plan numbering schemes accordingly.
- Useful for context numbers, sample numbers, or any sequential
  identifier where uniqueness matters more than semantics.
- Returns a padded string ("001"), not a number — this preserves
  leading zeros in exports and avoids numeric sorting issues.

---

## Date and Time Fields

### Date/Time with Now

- The recommended default for all timestamps. One tap captures the
  current date and time with timezone information, ensuring
  synchronisation safety across team members in different locations.
- Use for: observation timestamps, sample collection times, photo
  timestamps, any "when did this happen?" question.
- The captured timestamp uses the device clock — remind field teams to
  sync their device clocks before starting work each day.

### Date Picker

- For dates where the time component is unnecessary: excavation date,
  sample date, construction period, event date.
- Better than Date/Time with Now when recording historical or future
  dates (e.g., "Scheduled revisit date", "Date of last disturbance").
- The calendar picker interface helps users navigate to the correct
  date visually, which is especially useful for dates that are not
  "today".

### Date Time Picker

- Use only when both date AND time matter but the event is NOT the
  current moment (otherwise use Date/Time with Now).
- ⚠️ Does not store timezone information — risky for projects spanning
  multiple timezones. Prefer Date/Time with Now for timezone-sensitive
  data.
- Suitable for single-timezone projects recording specific event times
  (e.g., "tide time", "scheduled survey start").

### Month Picker

- Captures year and month only — useful for seasonal data, approximate
  dates, or periodic observations where day-level precision is
  unnecessary or misleading.
- Good for: "Season of fieldwork", "Month of last survey",
  "Approximate date of disturbance".
- Consider using Annotation with Month Picker to let collectors note
  whether the month is exact or approximate.

---

## Media Fields

### Take Photo

- Optimised for camera-first workflows: opens the device camera directly
  for immediate photo capture. Preferred over Attach File when photos
  are the primary media type.
- EXIF data (including GPS coordinates if available) is preserved —
  useful for spatial analysis but be aware of privacy implications if
  data will be shared publicly.
- Multiple photos can be attached to a single field. Consider how many
  photos per record are practical given storage and sync constraints.

### Attach File

- Accepts any file type — PDFs, spreadsheets, audio recordings, sketches.
  More flexible than Take Photo but less streamlined for camera workflows.
- Upload times vary significantly by file size and connection quality.
  In low-bandwidth field conditions, keep attached files small or defer
  uploads to when connectivity improves.
- Good for: scanned field notes, lab results, reference documents,
  audio recordings of oral descriptions.

---

## Location Fields

### Take GPS Point

- Captures a single coordinate using the device's GPS. Works best on
  mobile devices; desktop browsers provide less accurate location data.
- Consider setting an accuracy threshold (e.g., 10 metres) so that
  collectors wait for a good GPS fix rather than recording an
  inaccurate point.
- Enable Annotation for GPS points so collectors can note signal quality,
  obstacles (tree canopy, buildings), or whether the point was taken at
  the feature itself or offset.

### Map Input

- Enables drawing points, lines, and polygons on a map — ideal for
  site boundaries, transect routes, feature outlines.
- ⚠️ Requires internet for initial map tile loading. Offline map
  support is experimental and may have rendering issues. Plan
  accordingly for remote field locations.
- Best used on tablets or desktops where the screen is large enough
  for accurate drawing. Drawing precise polygons on a phone screen
  is difficult.

---

## Relationship Field

### Related Records

- The only way to create connections between records in Fieldmark.
  Essential for stratigraphic relationships, parent-child hierarchies
  (site → trench → context → find), and peer associations.
- Performance degrades above ~50 relationships per record. Design
  the data model to keep relationship counts manageable.
- Think carefully about relationship direction and semantics —
  "Context 5 cuts Context 8" is different from "Context 8 is cut by
  Context 5". Use vocabulary pairs to capture both directions.

---

## Display Field

### Rich Text

- Display-only — collectors cannot enter data into this field. Use it
  for instructions, warnings, section dividers, and procedural guidance
  embedded directly in the form.
- Supports Markdown formatting: **bold**, *italic*, headings, lists,
  and links. Use this to create clear, scannable guidance text.
- Place Rich Text fields at the top of sections to orient collectors
  before they begin entering data. Example: "Record all visible
  features in this trench section. Photograph before excavation."
- Keep text concise — field workers are typically reading in bright
  sunlight on a small screen. Short, imperative sentences work best.
