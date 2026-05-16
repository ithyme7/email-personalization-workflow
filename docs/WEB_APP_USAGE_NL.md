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
7. Volg de voortgang via de laadbalk.
8. Bekijk het dashboard voor review workload, visual confidence, friction types, quality flags en kosteninschatting.
9. Review en edit de rows in de `Review & Edit` tab.
10. Exporteer als CSV, XLSX, full workbook, client delivery export of naar Google Sheets.

## Demo mode

Gebruik `Demo sample` in de input-keuze om de workflow tijdens een call te laten zien zonder eerst een nieuw bestand klaar te zetten.

## Batch history

Elke run wordt lokaal opgeslagen in de history met datum, aantal rows, ready/review verdeling, model, tone profile, kosteninschatting en outputbestand. Vanuit de `History` tab kun je een eerdere workbook opnieuw laden of downloaden.

## Tone calibration

In `Tone Calibration` kun je feedback van een klant plakken, goede en slechte voorbeelden toevoegen en daar een nieuw client-specific profile van maken. Dit profile verschijnt daarna in de tone dropdown.

## Google Sheets

Publieke Google Sheets kunnen meestal direct via de URL worden gelezen.

Private Google Sheets hebben een service-account JSON nodig. Deel de Sheet met het service-account e-mailadres, upload de JSON in de app en kies eventueel de tabnaam.

Export naar Google Sheets werkt via dezelfde service-account methode.

## Kosteninschatting

De sidebar bevat input/output prijsvelden per 1M tokens. De app gebruikt de gemeten API-calls en token-schattingen uit de run om een batchkosten-inschatting te tonen.

Controleer provider pricing altijd voordat je marge of klantprijs bepaalt.

## Belangrijk

Zonder API key draait de app nog steeds als research/review workflow, maar worden er geen nieuwe AI-personalized lines gegenereerd.

Custom prompts worden gebruikt als tone guidance binnen de evidence-first regels. Ze mogen dus geen unsupported claims of hallucinations forceren.
