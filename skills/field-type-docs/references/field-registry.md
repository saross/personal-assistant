# Field Type Registry

Canonical mapping between internal component names, Designer UI names,
document slugs, and source files. Use this registry when generating or
updating field type documentation.

## Complete Field Registry

| # | Component Name | Designer UI Name | ADD A FIELD Tab | Doc Slug | Source File | Status |
|---|---------------|-----------------|-----------------|----------|-------------|--------|
| 1 | FAIMSTextField | FAIMS Text Field | TEXT | faims-text-field | text-fields-v05.md | Active |
| 2 | MultipleTextField | Multiline Text Field | TEXT | multiline-text-field | text-fields-v05.md | Active |
| 3 | Email | Email Field | TEXT | email-field | text-fields-v05.md | Active |
| 4 | Select | Select Field | CHOICE | select | select-choice-fields-v05.md | Active |
| 5 | MultiSelect | Select Multiple | CHOICE | multi-select | select-choice-fields-v05.md | Active |
| 6 | RadioGroup | Select one option | CHOICE | radio-group | select-choice-fields-v05.md | Deprecated |
| 7 | Checkbox | Checkbox | CHOICE | checkbox | select-choice-fields-v05.md | Active |
| 8 | AdvancedSelect | Select Field (Hierarchical) | CHOICE | hierarchical-select | select-choice-fields-v05.md | Beta |
| 9 | NumberField | Number Input | NUMBERS | number-input | number-fields-v05.md | Active |
| 10 | ControlledNumber | Controlled Number | NUMBERS | controlled-number | number-fields-v05.md | Active |
| 11 | BasicAutoIncrementer | Unique ID | NUMBERS | unique-id | number-fields-v05.md | Active |
| 12 | DateTimeNow | Date/Time with Now | DATE & TIME | date-time-now | datetime-fields-v05.md | Active |
| 13 | DatePicker | Date Picker | DATE & TIME | date-picker | datetime-fields-v05.md | Active |
| 14 | DateTimePicker | Date Time Picker | DATE & TIME | date-time-picker | datetime-fields-v05.md | Active |
| 15 | MonthPicker | Month Picker | DATE & TIME | month-picker | datetime-fields-v05.md | Active |
| 16 | TakePhoto | Take Photo | MEDIA | take-photo | media-fields-v05.md | Active |
| 17 | FileUploader | Attach File | MEDIA | attach-file | media-fields-v05.md | Active |
| 18 | TakePoint | Take GPS Point | LOCATION | take-gps-point | location-fields-v05.md | Active |
| 19 | MapFormField | Map Input | LOCATION | map-input | location-fields-v05.md | Active |
| 20 | RelatedRecordSelector | Related Records | RELATIONSHIP | related-records | relationship-field-v05.md | Active |
| 21 | RichText | Rich Text | DISPLAY | rich-text | display-field-v05.md | Active |
| 22 | TemplatedStringField | Templated String | TEXT | templated-string | text-fields-v05.md | Active |
| 23 | QRCodeFormField | QR / Barcode Scanner | TEXT | qr-barcode-scanner | text-fields-v05.md | Mobile Only |
| 24 | AddressField | Address | TEXT | address | text-fields-v05.md | Beta |

## Tab Contents Summary

Quick reference for which fields appear under each ADD A FIELD tab:

| Tab | Fields |
|-----|--------|
| **ALL** | All 24 field types |
| **TEXT** | FAIMS Text Field, Multiline Text Field, Email Field, Templated String, QR / Barcode Scanner, Address |
| **NUMBERS** | Number Input, Controlled Number, Unique ID |
| **DATE & TIME** | Date/Time with Now, Date Picker, Date Time Picker, Month Picker |
| **MEDIA** | Take Photo, Attach File |
| **LOCATION** | Take GPS Point, Map Input |
| **CHOICE** | Checkbox, Select Multiple, Select one option, Select Field, Select Field (Hierarchical) |
| **RELATIONSHIP** | Related Records |
| **DISPLAY** | Rich Text |

## Notes

- Designer UI names were verified against the live staging server
  (web.test.fieldmark.app) in February 2026
- The CHOICE tab requires scrolling right via the **›** arrow button;
  it is not visible in the default tab bar width
- "Select one option" (RadioGroup) appears in the CHOICE tab but is
  deprecated — the design doc should include a deprecation warning
- RadioGroup card text is "Select one option"; helper text beneath
  the card is "Single choice radio button set". User-facing docs must
  use the card text ("Select one option"), not the helper text — do
  NOT refer to this field as "radio button group" or "Radio Buttons"
- Source files are located in `production/inputs/field-categories/`
- The secondary source `production/inputs/patterns/field-selection-guide.md`
  contains practical guidance for choosing between field types
