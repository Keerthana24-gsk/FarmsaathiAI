# FarmSaathi AI v6.1

FarmSaathi AI is a Flask-based agricultural advisory prototype with a farmer-first registration flow and a responsive dashboard.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## New farmer onboarding and dashboard

1. A new visitor first sees the registration screen.
2. The farmer enters their full name and 10-digit Indian mobile number.
3. After registration, the dashboard opens with the farmer profile, farm details, soil health, crop planning and existing-crop-management options.
4. The profile is saved in the browser's local storage for this prototype. Returning to the same browser opens the saved profile; **Switch farmer** clears it and returns to registration.

**Prototype limitation:** this is not production authentication. No OTP/SMS verification is sent, and registration details are stored in that browser rather than in a secure central farmer database. Add verified phone authentication, consent, secure server-side storage and a privacy policy before real public deployment.

## Existing capabilities

- Crop planning and existing crop management
- Soil Health Card upload and nutrient inputs
- Weather-aware irrigation guidance and alerts
- Crop suitability, fertilizer estimates and profitability estimates
- Seven specialist advisory agents coordinated by a master coordinator
- English, Hindi, Kannada and Telugu interface labels
- Browser voice input and speech output where supported
- Offline app-shell caching and last-advice caching

## Important validation notes

The crop recommendation profiles and several agronomic/economic values are illustrative prototype values. Replace them with validated local datasets and ICAR/KVK recommendations before presenting accuracy or yield claims. Validate irrigation calculations against FAO-56/CROPWAT and test the Soil Health Card reader on multiple real cards.

## Farmer profile and farm details (v6.2)
- The dashboard profile now includes a separate **Delete profile** action with a confirmation prompt. Deleting removes the saved farmer profile and cached advice from the current browser only.
- Farmer name and mobile number can be edited and saved; the mobile number is validated as 10 digits.
- Additional farm context fields are available: land ownership, water/irrigation source, irrigation method, previous crop, sowing season, and farming practice. Existing soil type, soil moisture, pH, N-P-K, land area, rainfall, and crop-price inputs remain available in the advice form.
- These new farm-context fields are currently saved with the local farmer profile for record-keeping. They are not yet used by the advice calculation engine; the existing advice logic continues to use its established inputs.


## Farmer login and logout (v6.4)

- A farmer registers with their name and 10-digit mobile number.
- The dashboard remains active while the browser tab session is active, including page refreshes.
- The **Log out** button returns the farmer to the registration screen.
- Logging out keeps the saved farmer and farm details in that browser, so the same name and mobile number restore the existing farm profile on the next registration/return.
- **Switch farmer** clears the current saved profile so a different farmer can register.
- **Delete profile** removes the saved profile and cached advice from the current browser.
- This is a local prototype flow, not secure account authentication: no OTP/SMS verification or central user database is configured. Do not use it to protect sensitive data.


## India-wide location dropdowns (v6.5)

The Farm Details location fields now use dependent dropdowns:
1. State / Union Territory
2. District (loaded for the selected state)
3. Village / Town / City (loaded for the selected district where the data service provides records)

The state, district and sub-district hierarchy is loaded from an LGD-derived public API. Village and urban local-body records are requested from a second LGD-derived public API. If a village/city listing is unavailable for a district, the interface falls back to that district's LGD sub-districts (taluk/tehsil/mandal) rather than inventing village names.

The dropdowns require an internet connection to retrieve location records. The data services are independent community mirrors, not government-operated endpoints. For production deployment, periodically download and host the official Local Government Directory (LGD) export locally to avoid dependence on public API uptime/rate limits and to provide a fully offline location catalogue.

Sources:
- Ministry of Panchayati Raj, Local Government Directory: https://lgdirectory.gov.in/
- LGD hierarchy API documentation: https://india-lgd-index-api.vercel.app/
- LGD-derived cities/villages API documentation: https://lgd-json-api.vercel.app/docs

The registration screen now asks for the preferred language before the farmer enters their name and mobile number. The same preference is copied to the dashboard language setting.


## Blank registration form (v6.6)

The registration screen now always opens with blank farmer name and mobile-number fields. Existing saved profile data is not copied into the registration form. Browser autocomplete is disabled on the registration form and identity inputs; browser-level autofill settings may still override website hints in some configurations.


## Location dropdown correction (v6.7)

Fixed a cascading-dropdown identifier bug: the first implementation displayed state and district names but also sent those names to the LGD API, which requires numeric LGD codes. State and district dropdown option values now use the returned LGD codes while labels remain readable names. Profile persistence maps selected codes back to names and stores both names and codes.

Added a secondary district/state lookup using the documented `/api/states` and `/api/districts?stateCode=...` endpoints from the LGD-derived Indian Cities API if the primary hierarchy API fails. Village requests use `/api/villages?districtCode=...`; urban local bodies use `/api/cities?districtCode=...` as fallback. The LGD hierarchy API documents numeric state/district codes, while the second service documents the `stateCode` and `districtCode` query parameters.

Public API uptime, rate limits, and completeness are outside the app's control. Village data may not be enabled or complete for every district; in that case the app falls back to sub-district names (taluk/tehsil/mandal). The app requires internet access for live dropdown data.

Documentation:
- https://india-lgd-index-api.vercel.app/docs
- https://lgd-json-api.vercel.app/openapi.json
- https://lgdirectory.gov.in/


## Dashboard layout cleanup (v6.8)

Improved dashboard sizing so the advice panel and its cards fit within the available browser width without horizontal page scrolling. The two dashboard columns now shrink safely and stack at narrower desktop/tablet widths; advice cards, profit/fertilizer grids and forecast tables are constrained to their parent panel and long text wraps. Removed the extra “Online: live weather can be requested” status strip and the “Your AI farm team” agent-summary cards from the advice output to keep the farmer-facing screen focused on actionable farm guidance. The underlying weather, crop, irrigation, soil, fertilizer and profitability advice functions remain unchanged.


### Multilingual behaviour (v7.0)
The selected language is applied to dashboard labels and the supported offline advice phrase catalogue for Hindi, Kannada and Telugu. Crop names, place names, scientific abbreviations and numeric measurements remain unchanged. Any advice phrase not yet present in the offline phrase catalogue remains in English; review translations with native speakers before operational use.


## Language rendering fix (v7.1)
- Reworked dashboard language application to translate farm-area labels, land ownership, water source, irrigation method, previous crop, season, farming practice, placeholders and select options by stable option values.
- Reapplies translations after the selected language is applied so dashboard fields do not remain in English after registration or profile changes.
- The entered crop name, place names, numeric values and scientific abbreviations remain unchanged.


## v7.2 language behaviour
The selected language is now applied to the registration screen, dashboard labels, form controls, common dropdown options, status messages, and dynamically inserted interface text. Generated advice uses the built-in phrase translations and localized forecast summary for Hindi, Kannada, and Telugu. Crop and place names, scientific abbreviations, and numeric values remain unchanged where this improves clarity. Unrecognized free-text advice may remain in English; this offline prototype does not claim unrestricted machine translation.


## Version 7.4 – multilingual coverage update
- Added Hindi, Kannada and Telugu labels for common crop names, soil types and crop stages throughout dynamically rendered result cards.
- Added translations for crop suitability summaries and generated advice containing common crop names.
- The Previous crop field recognizes common English crop names and aliases (for example, `raagi`, `ragi`, `maize`) and displays their localized names after the field loses focus. Multiple comma-separated crop names are supported.
- Unknown names are preserved rather than guessed. Arbitrary free-form English sentences are not machine-translated offline; use the supported crop vocabulary or add reviewed translations to the dictionaries.
- Bumped the service-worker cache version to prevent stale v7.2 UI assets from being reused.


## Version 7.5 – complete dynamic UI localization
- Localizes the dynamically generated crop, soil and crop-stage tiles and their short descriptions in Hindi, Kannada and Telugu.
- Localizes state/district/village dropdown placeholders while preserving official administrative place names.
- Localizes crop names in both crop-ranking and suitability cards, fertilizer bag names, small water-moisture labels, and forecast table headings in all supported languages.
- Keeps scientific abbreviations such as ET₀, N, P₂O₅ and K₂O intact; these are standard scientific notation.
- Switching back to English restores English labels.


## Version 7.6 – expanded crop selector and alert localization
- Replaced the six-crop tile chooser with a visible dropdown that lists all available crop choices.
- Added Ragi, Groundnut, Soybean, Chickpea, Sorghum, Pearl Millet, Potato, Onion, Chilli and Banana.
- Localized the crop dropdown labels in English, Hindi, Kannada and Telugu while preserving canonical English values internally for model calculations.
- Added illustrative crop water-coefficient, soil/season suitability, model profile and economics defaults for the additional crops. These values are demo estimates and must be checked against local agricultural recommendations and market prices.
- Added Hindi, Kannada and Telugu text for the seven-day soil-water alert detail and the sample-data status chip.


## Version 7.7 – language-selection and advice translation fixes
- The registration language selector now immediately applies the chosen language to the entire page and synchronizes both language selectors.
- An old saved profile language no longer overrides the language selected on a fresh registration screen.
- Fixed a v7.6 translation dictionary merge bug that had replaced earlier Hindi/Kannada/Telugu advice phrases, causing mixed-language results.
- Added translations for generated irrigation action labels, next-step messages, tomato crop-care tasks and soil-care advice in Hindi, Kannada and Telugu.
- Bumped the service-worker cache version so browsers fetch the updated dashboard.


## Version 7.8 – strict selected-language advice refresh
- Changing the app language now re-requests the current farm advice from the backend using the newly selected language.
- Prevents previously rendered advice HTML from another language being shown as an offline fallback.
- Added numeric weather-alert translations for Hindi, Kannada and Telugu (heatwave, frost, heavy rain, strong wind and hot/dry spell).
- Removed the duplicate advice refresh on the profile language selector.
- Updated service-worker cache version and clears old app shell caches on activation.


## Version 7.9 – crop-stage recommendation translations
- Added complete Hindi, Kannada and Telugu translations for the generated crop-stage tasks of Rice, Wheat, Maize, Tomato, Cotton and Sugarcane.
- Specifically fixes the Rice instruction about weeding at 20–25 days, urea top-dressing at tillering and stem-borer scouting.
- Added localized versions of the other crop stage instructions so the generated next-step and crop-care cards no longer fall back to English for these core crops.
- Added translation handling for generic stage-task templates used by the expanded crop catalogue.
- Updated the service-worker cache version to force browsers to fetch the latest translation data.


## Version 7.10 – reliable English language reset
- Added a complete English translation dictionary for profile, farm-detail labels, select options, helper text and dashboard controls.
- Fixed language switching so selecting English restores English labels and dropdown values after Hindi, Kannada or Telugu was selected.
- Added English placeholders and location help text, preventing Telugu/Hindi/Kannada helper text from persisting.
- Synchronized the registration, profile and application language selectors.
- Bumped the service-worker cache to v7.10 so browsers fetch the corrected frontend.


## Version 7.11 – crop dropdown visibility
- Fixed the crop selector being rendered at its intrinsic arrow-only width by applying the shared full-width field styling.
- Added a visible loading option while the crop list is fetched.
- Kept the existing canonical crop values and selected-language option translation.
- Bumped the service-worker shell cache version.


## Version 7.12 – crop list loading fallback
- Added a client-side fallback crop catalogue (16 crops plus AI selection) when the `/api/options` request fails.
- The dropdown and crop tiles now remain usable instead of being stuck at “Loading crops…”.
- Fallback crop options pass through the existing selected-language localization function.
- Added safe defaults for soil, stage and NPK controls during an options API outage.
- Bumped the service-worker cache version.


## Version 7.13 – always-visible crop options
- The crop dropdown is now populated directly in the HTML with AI selection and 16 crop options.
- Crop choices are visible immediately and no longer depend on `/api/options` responding.
- Existing API population and selected-language localization remain in place.
- Bumped the service-worker cache version to avoid stale page assets.


## Version 7.14 – dashboard advice submit and profile restore
- Added a capture-phase submit guard for the dashboard form so Generate Advice cannot trigger a native GET navigation to `/`.
- Kept the existing async `/api/advice` handler responsible for generating recommendations.
- Restores a valid saved farmer profile after refresh even if sessionStorage was cleared or unavailable; explicit logout still clears the active session and shows registration.
- Bumped the service-worker shell cache version.


## Version 7.15 – nutrient controls and advice generation reliability
- N/P/K Low, Medium and High segmented controls are rendered immediately, not only after the options API responds.
- Crop, soil and growth-stage selectors now initialise from built-in fallback options if `/api/options` fails.
- The advice button shows a generating state and is restored after success or failure.
- Advice connection/JSON errors are displayed in the results area; Flask internal errors return JSON and are logged in the terminal.
- Service-worker cache bumped to v7.15.


## Version 7.16 – reliable farm-mode and nutrient controls
- Added static Low/Medium/High controls and default select values for N, P and K.
- Added independent click handlers so the controls work even if the options API or main initialisation fails.
- Added direct working handlers for “I want to sow” and “Crop is growing”.
- Added fallback soil and crop-stage choices so these controls are not left blank during API failures.
- Bumped the service-worker cache to v7.16.


## Version 7.17 – direct farm controls
- N/P/K rows now contain Low, Medium and High buttons in the HTML itself, not only after API-driven rendering.
- Each nutrient button directly updates its corresponding form value.
- Sowing / crop-growing buttons directly update the hidden status field and crop-stage visibility.
- The selected crop-growing state switches Auto crop to Rice only when no crop has been selected.
- Updated service-worker cache identifier.


## Version 7.25 – offline weather chip language fix
- Fixed the irrigation result's offline-weather metadata chip so it follows the currently selected language, including English.
- Preserves the location name (for example, Bengaluru) when translating the offline sample-data note.
- Stores the original metadata text so switching between English, Hindi, Kannada and Telugu remains reversible.
- Updated the service-worker cache identifier to v7.25 so the browser does not keep the previous frontend.
