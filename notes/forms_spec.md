# Forms spec — `client_referral` and `provider_availability`

Snapshot of both intake forms as they exist today. Both are `kind`-discriminated `Post` subclasses; both submit to `POST /posts` (create) and `PATCH /posts/{id}` (edit). Required unless marked optional. No PII anywhere — both forms remind the user of this in a hint.

---

## Shared enums

| Tuple | Values |
|---|---|
| `US_STATES` | 50 USPS abbreviations + `DC` (51 total) |
| `LOCATION_AVAILABILITY_OPTIONS` | `yes`, `no`, `please_contact` |
| `CLIENT_AGE_GROUPS` | `children_0_5`, `children_6_10`, `preteens_11_13`, `adolescents_14_18`, `young_adults_19_24`, `adults_25_64`, `older_adults_65_plus` |
| `LANGUAGE_PREFERRED_OPTIONS` | `no`, `yes` (CR uses for "preferred"; PA uses for "offered in non-English") |
| `CLIENT_REFERRAL_SERVICES` | `evaluation`, `medication_management`, `psychotherapy`, `case_management`, `allied_health` |
| `INSURANCE_OPTIONS` | `in_network`, `out_of_network`, `in_and_out_of_network` |
| `TREATMENT_SETTINGS` | `outpatient`, `iop`, `crisis_care`, `php`, `residential` |
| `DESIRED_TIME_SLOTS` | 21 tokens: `<day>_<slot>` for day ∈ {monday…sunday} × slot ∈ {morning, afternoon, evening} |

ZIP: 5 digits, regex `^\d{5}$`. Free-text fields strip whitespace; required ones reject empty/whitespace-only.

---

## Form 1 — `client_referral`

A clinician requesting placement / referral support for a client.

### Section 1 — client location

| Field | Type | Req | Notes |
|---|---|---|---|
| `location_city` | text | ✓ | |
| `location_state` | select → `US_STATES` | ✓ | |
| `location_zip` | text (5-digit) | ✓ | |
| `location_in_person` | select → `LOCATION_AVAILABILITY_OPTIONS` | ✓ | "In-Person Sessions" |
| `location_virtual` | select → `LOCATION_AVAILABILITY_OPTIONS` | ✓ | "Virtual Sessions" |
| `desired_times` | 7×3 checkbox grid → `list[DESIRED_TIME_SLOTS]` | optional | Empty list allowed |

### Section 2 — demographics

| Field | Type | Req | Notes |
|---|---|---|---|
| `client_dem_ages` | select → `CLIENT_AGE_GROUPS` | ✓ | "Age Group" |
| `language_preferred` | select → `LANGUAGE_PREFERRED_OPTIONS` | ✓ | "Services preferred in language other than English?" Default `no` |

### Section 3 — description

| Field | Type | Req | Notes |
|---|---|---|---|
| `description` | textarea | ✓ | "no PII" hint |

### Section 4 — services

| Field | Type | Req | Notes |
|---|---|---|---|
| `services` | 5-checkbox multi-select → `list[CLIENT_REFERRAL_SERVICES]` | optional | Empty list allowed |
| `services_psychotherapy_modality` | text | optional | Free text (e.g. "DBT", "EMDR"); only meaningful when `psychotherapy` ticked |

### Section 5 — insurance

| Field | Type | Req | Notes |
|---|---|---|---|
| `insurance` | select → `INSURANCE_OPTIONS` | ✓ | "Payment situation" |

---

## Form 2 — `provider_availability`

A provider listing open slots / featured services. No client info.

### Section 1 — provider information

| Field | Type | Req | Notes |
|---|---|---|---|
| `practice_name` | text | ✓ | |
| `available_providers` | text | ✓ | Free text — names or count of available clinicians |

### Section 2 — location

| Field | Type | Req | Notes |
|---|---|---|---|
| `location_city` | text | ✓ | |
| `location_state` | select → `US_STATES` | ✓ | |
| `location_zip` | text (5-digit) | ✓ | |

### Section 3 — availability

| Field | Type | Req | Notes |
|---|---|---|---|
| `in_person_sessions` | select → `LOCATION_AVAILABILITY_OPTIONS` | ✓ | |
| `virtual_sessions` | select → `LOCATION_AVAILABILITY_OPTIONS` | ✓ | |
| `desired_times` | 7×3 checkbox grid → `list[DESIRED_TIME_SLOTS]` | optional | Empty list allowed |

### Section 4 — featured services

| Field | Type | Req | Notes |
|---|---|---|---|
| `services` | 5-checkbox multi-select → `list[CLIENT_REFERRAL_SERVICES]` | ✓ | **Min 1 selection** |
| `treatment_modality` | text | optional | Free text (e.g. "DBT", "EMDR") |
| `settings` | 5-checkbox multi-select → `list[TREATMENT_SETTINGS]` | ✓ | **Min 1 selection** |
| `client_focus` | textarea | ✓ | "no PII" hint |
| `age_group` | select → `CLIENT_AGE_GROUPS` | ✓ | |
| `non_english_services` | select → `LANGUAGE_PREFERRED_OPTIONS` | optional | Default `no` |

### Section 5 — insurance

| Field | Type | Req | Notes |
|---|---|---|---|
| `payment_situation` | select → `INSURANCE_OPTIONS` | ✓ | |
| `sliding_scale` | radio (`true` / `false`) | ✓ | Coerced to bool |
| `cost` | text | optional | Free-text cost description |

---

## Field-name overlap (intentional reuse vs. divergence)

| Concept | CR field | PA field |
|---|---|---|
| City | `location_city` | `location_city` |
| State | `location_state` | `location_state` |
| ZIP | `location_zip` | `location_zip` |
| In-person availability | `location_in_person` | `in_person_sessions` |
| Virtual availability | `location_virtual` | `virtual_sessions` |
| Time grid | `desired_times` | `desired_times` |
| Service multi-select | `services` | `services` |
| Free-text modality | `services_psychotherapy_modality` | `treatment_modality` |
| Age group | `client_dem_ages` | `age_group` |
| Language | `language_preferred` | `non_english_services` |
| Insurance / payment | `insurance` | `payment_situation` |
| Long-form description | `description` | `client_focus` |

Same column names → same DB column types and the audit-snapshot model can carry one entry per concept.

---

## Cross-cutting behaviors

- **Wire format**: JSON. Multi-select arrays use a custom `json-enc-arrays` HTMX extension (in `src/templates/base.html`) so 0/1/2+ checkboxes always serialize as `[]` / `[x]` / `[x,y]`. The list of always-array fields swaps per kind on the radio toggle (CR: `desired_times services`; PA: `desired_times services settings`) so the off-kind's array fields don't leak into the body.
- **Bool radios** for `sliding_scale` (and historically `accepting_new_clients`): `value="true"` / `value="false"` strings, Pydantic coerces to bool.
- **Whitespace**: required text fields strip and reject empty; optional text fields strip and become `None` when empty.
- **Discriminator**: `kind` field on every payload. PATCH body's `kind` must echo the persisted post's kind (the route also enforces this).
- **`extra="forbid"`**: every per-kind schema rejects unknown fields with a 422.
- **PATCH no-op**: every Update variant requires at least one editable field; an empty PATCH 422s.
- **Edit prefill**: per-kind partial accepts an optional `post` context object; selects/checkboxes mark `selected`/`checked` against its attributes.
- **Single source of truth for enums**: tuples in `src/models/post.py`. The DB CHECK constraints render from them; a guardrail test (`test_schema_literals_match_model_tuples`) asserts the schema's `Literal[...]`s match.
