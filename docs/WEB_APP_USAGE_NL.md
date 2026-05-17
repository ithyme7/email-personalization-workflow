# Webapp Gebruiken

## Starten

```bash
streamlit run web_app.py
```

Open daarna:

```text
http://localhost:8501
```

Of dubbelklik op:

```text
Start_Email_Personalizer_Web_App.bat
```

De launcher kiest automatisch `localhost:8501`, of de volgende vrije poort als 8501 al bezet is.

## Workflow

1. Upload een CSV, laad een Google Sheet, of kies de demo sample.
2. Vul de campaign context in.
3. Kies een model provider, model en eventueel API key in de sidebar.
4. Kies een tone profile uit de 50 presets.
5. Maak optioneel een klant-specifiek tone profile.
6. Klik op `Run batch`.
7. Volg de voortgang via de laadbalk. De run draait op de achtergrond, zodat de app status kan blijven tonen in plaats van te bevriezen.
8. Bekijk het dashboard voor sendability, review workload, visual confidence, friction types, quality flags en kosteninschatting.
9. Review en edit de rows in de `Review & Edit` tab.
10. Zet per rij eventueel `human_decision`, `edited_line`, `edit_reason_category` en `edit_notes`.
11. Sla goede/mislukte menselijke edits optioneel op als goldset.
12. Gebruik eventueel `Client Training` om een simpele feedback-template voor de klant te maken.
13. Check optioneel de `Evals` tab als je een frozen eval set hebt.
14. Exporteer als CSV, XLSX, full workbook, client delivery export, client-safe package of naar Google Sheets.

## Demo mode

Gebruik `Demo sample` in de input-keuze om de workflow tijdens een call te laten zien zonder eerst een nieuw bestand klaar te zetten.

## Batch history

Elke run wordt lokaal opgeslagen in de history met datum, aantal rows, ready/review verdeling, model, tone profile, kosteninschatting en outputbestand. Vanuit de `History` tab kun je een eerdere workbook opnieuw laden of downloaden.

De history gebruikt nu lokaal SQLite in plaats van alleen losse JSONL-regels. Dat maakt de app-state stabieler wanneer je vaker batches draait of de app opnieuw opent.

## Tone calibration

In `Tone Calibration` kun je feedback van een klant plakken, goede en slechte voorbeelden toevoegen en daar een nieuw client-specific profile van maken. Dit profile verschijnt daarna in de tone dropdown.

## Snelle Review

In `Review & Edit` staat boven de tabel een snelle review-panel.

Links zie je:

- het gevonden bewijs
- bronlinks
- hard-fail en soft-edit redenen
- flags en review-notes

Rechts zie je:

- de volledige e-mailpreview
- de huidige personalization line
- jouw beslissing
- een editveld
- de reden en notes

Gebruik dit panel voor de eerste kwaliteitsronde. De grote tabel blijft beschikbaar voor bulk edits en controle.

## Sendability gate

De app maakt nu onderscheid tussen gewone status en sendability:

- `Send`: sterk genoeg om mee te nemen in client delivery.
- `Edit`: bruikbaar uitgangspunt, maar eerst handmatig aanscherpen.
- `Reject`: niet versturen, want bewijs of copy is nog niet betrouwbaar genoeg.

De gate let onder andere op unsupported claims, em dashes, genericness, technische audit-taal, verkeerde surface, te lange zinnen, ontbrekende outcome-link en lage visual confidence.

De gate is opgesplitst in meerdere dimensies:

- `hard_fail_reasons`: redenen waardoor je de line niet moet versturen.
- `soft_edit_reasons`: redenen waardoor de line nog bewerkt moet worden.
- `evidence_score`: hoe sterk de bron/evidence is.
- `copy_quality_score`: hoe goed de line zelf leest.
- `outcome_alignment_score`: link met activation, conversion, bookings, retention of drop-off.
- `template_fit_score`: of de line logisch doorloopt in de pitch.
- `surface_correctness`: of de gekozen observatie past bij het type bedrijf/product.
- `visual_reliability_score`: hoe betrouwbaar de visuele/UX-observatie is.
- `viewport_scope`: of een visuele claim op mobiel, desktop, beide of onbekend bewijs steunt.
- `evidence_scope`: of de rij bronlinks, screenshots, beide of dun bewijs heeft.
- `privacy_flags`: interne waarschuwingen zoals traces of lokale paden die niet naar een client moeten.

Hard-fail redenen blokkeren delivery. Soft-edit redenen betekenen meestal dat de rij herschrijfbaar is.

## Human edit goldset

In `Review & Edit` kun je per rij aangeven wat jij als mens beslist:

- `human_decision`
- `edited_line`
- `edit_reason_category`
- `edit_notes`

Kies daarna waar je de review wilt opslaan:

- `reviewed_examples`: normale menselijke reviewdata.
- `frozen_eval_set`: vaste testset om nieuwe prompts/modellen tegen te meten.
- `candidate_training_set`: voorbeelden die later mogelijk bruikbaar zijn voor training/fine-tuning.

Klik daarna op `Save reviewed rows to goldset`. De app bewaart die voorbeelden lokaal in:

```text
data/goldset/reviewed_examples.csv
data/goldset/frozen_eval_set.csv
data/goldset/candidate_training_set.csv
```

Die goldset kun je later gebruiken om tone profiles, prompts, modelkeuze en pairwise evaluaties te verbeteren.

## Client Training

De `Client Training` tab maakt het trainen simpel voor een klant.

De klant hoeft alleen dit in te vullen:

- `Send as is`: deze line zou ik zo versturen.
- `Rewrite`: deze line is bijna goed, maar schrijf hem zo.
- `Reject`: deze line moet niet gebruikt worden.

Als de klant `Rewrite` kiest, is `client_rewrite` het belangrijkste veld. Dat wordt later de preferred output. De originele line wordt dan de non-preferred output.

De template bevat ook uitleg en voorbeeldrijen, zodat de klant geen technische termen zoals evals, DPO of fine-tuning hoeft te begrijpen.

Na uploaden zet de app de ingevulde feedback automatisch om naar een goldset.

## Campagneresultaten Importeren

In `Client Training` kun je ook een post-send feedback template downloaden.

Vul daarin na een campagne simpele uitkomsten in:

- `sent`
- `opened`
- `replied`
- `positive_reply`
- `booked`
- `bad_fit_or_bounce`
- `notes`

Upload het ingevulde bestand daarna terug in de app. De resultaten worden lokaal opgeslagen in:

```text
data/campaign_feedback/campaign_results.csv
```

Dit traint nog geen model automatisch. Het zorgt er wel voor dat je later kunt meten welke soort lines, surfaces en evidence echt betere replies of bookings opleveren.

## Evals

In de `Evals` tab meet de app de huidige sendability-gate tegen je `frozen_eval_set`.

De belangrijkste metrics:

- agreement tussen gate en jouw menselijke beslissing
- send precision
- false sends
- reject recall
- surface correctness

Gebruik dit vooral voordat je prompts, thresholds of modelkeuze verandert.

## Client-safe package

Gebruik in de `Export` tab bij voorkeur `Create client-safe delivery package` voor externe levering.

Die package bevat:

- opgeschoonde CSV
- opgeschoonde XLSX
- geselecteerde screenshots als ze beschikbaar zijn

Die package bevat niet:

- raw Playwright traces
- raw detector output
- interne auditdetails
- lokale bestandspaden zoals `C:\Users\...`

De package maakt ook een `manifest.json` en scant tekstvelden op lokale paden, API-key-achtige waarden, tokenized URL's, e-mails en telefoonnummers. Screenshots worden alleen meegenomen als ze door de privacy-scan komen.

Standaard staat `REQUIRE_SCREENSHOT_OCR=true`. Dat betekent: als lokale OCR niet klaarstaat, worden screenshots overgeslagen in de client-safe package in plaats van blind meegestuurd. Check dit met:

```bash
python tools/check_ocr.py
```

Gebruik `REQUIRE_SCREENSHOT_OCR=false` alleen voor lokale/interne debugging, niet voor klantlevering.

## Google Sheets

Publieke Google Sheets kunnen meestal direct via de URL worden gelezen.

Private Google Sheets hebben een service-account JSON nodig. Deel de Sheet met het service-account e-mailadres, upload de JSON in de app en kies eventueel de tabnaam.

Export naar Google Sheets werkt via dezelfde service-account methode.

## Kosteninschatting

De sidebar bevat input/output prijsvelden per 1M tokens. De app gebruikt de gemeten API-calls en token-schattingen uit de run om een batchkosten-inschatting te tonen.

Controleer provider pricing altijd voordat je marge of klantprijs bepaalt.

Voor harde kostenbewaking kun je in `.env` instellen:

```text
MAX_BATCH_COST_USD=0
MAX_LLM_CALLS_PER_BATCH=0
```

`0` betekent uitgeschakeld. Als je hier limieten invult, stopt de workflow vóór de volgende API-call zodra de batch daaroverheen dreigt te gaan.

## Browser Robustheid

Voor sites die tijdelijk blokkeren, traag laden of dynamisch renderen kun je browser-retries en optionele browserconfig instellen:

```text
BROWSER_RETRY_ATTEMPTS=3
BROWSER_PROXY_URL=
BROWSER_USER_AGENT=
```

Laat `BROWSER_PROXY_URL` leeg tenzij je een legitieme proxy voor je eigen workflow hebt. Dit is bedoeld om tijdelijke failures en rate-limit ruis te verminderen, niet om toegang te forceren.

## Belangrijk

Zonder API key draait de app nog steeds als research/review workflow, maar worden er geen nieuwe AI-personalized lines gegenereerd.

Custom prompts worden gebruikt als tone guidance binnen de evidence-first regels. Ze mogen dus geen unsupported claims of hallucinations forceren.

## Nieuwe app-first research regel

Als de tool een mobiele app detecteert, krijgt app/onboarding voorrang boven blogs of algemene site-observaties.

Volgorde:

1. App Store / Google Play listing.
2. Screenshots.
3. Publieke review complaints, wanneer beschikbaar.
4. Onboarding permissions.
5. Signup requirement.
6. Paywall, subscription of access-code.
7. Daarna pas website/landing page.

De tool classificeert leads als `app_first_product`, `website_first_leadgen`, `b2b_service`, `commerce_product_page` of `marketplace_booking_flow`.

## UX validators

De detectors mogen intern dingen vinden zoals contrast, tap targets, horizontal overflow, CTA below fold, broken links, Lighthouse issues of axe-core issues.

Maar de email-copy moet menselijk blijven. Dus niet:

`The CTA has a low contrast ratio.`

Maar wel:

`I was checking the mobile page and the main CTA was easy to miss on first load...`

## Deelbare screenshots

Als screenshots of traces worden gemaakt, komen die naast de output workbook in een assets-map en delivery zip:

```text
<output_name>_assets/
<output_name>_delivery_package.zip
```

Gebruik de zip als je screenshots of visueel bewijs met iemand anders wil delen.
