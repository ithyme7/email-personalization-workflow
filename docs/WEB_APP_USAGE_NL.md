# Webapp Gebruiken

## Starten

```bash
streamlit run web_app.py
```

Open daarna:

```text
http://localhost:8501
```

## Workflow

1. Upload een CSV.
2. Vul de campaign context in.
3. Kies een model provider, model en eventueel API key in de sidebar.
4. Kies een tone profile uit de 50 presets.
5. Maak optioneel een custom prompt/profile.
6. Klik op `Run batch`.
7. Review en edit de rows in de `Review & Edit` tab.
8. Exporteer als CSV, XLSX of full workbook.

## Belangrijk

Zonder API key draait de app nog steeds als research/review workflow, maar worden er geen nieuwe AI-personalized lines gegenereerd.

Custom prompts worden gebruikt als tone guidance binnen de evidence-first regels. Ze mogen dus geen unsupported claims of hallucinations forceren.
