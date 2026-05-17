from __future__ import annotations

from typing import Any

import pandas as pd


SENDING_TOOL_PRESETS = {
    "generic": {
        "first_name": "first_name",
        "last_name": "last_name",
        "full_name": "person",
        "company": "company",
        "role": "role",
        "website": "website",
        "personalized_line": "personalized_line",
        "evidence": "evidence_found",
        "source_urls": "source_urls",
    },
    "lemlist": {
        "firstName": "first_name",
        "lastName": "last_name",
        "companyName": "company",
        "jobTitle": "role",
        "website": "website",
        "icebreaker": "personalized_line",
    },
    "instantly": {
        "first_name": "first_name",
        "last_name": "last_name",
        "company_name": "company",
        "job_title": "role",
        "website": "website",
        "personalization": "personalized_line",
    },
    "smartlead": {
        "first_name": "first_name",
        "last_name": "last_name",
        "company_name": "company",
        "position": "role",
        "website": "website",
        "personalization": "personalized_line",
    },
}


def preset_names() -> list[str]:
    return list(SENDING_TOOL_PRESETS)


def _split_name(value: Any) -> tuple[str, str]:
    parts = str(value or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df:
        return df[column].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _prepared_delivery_df(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    if {"human_decision", "edited_line", "personalized_line"}.issubset(prepared.columns):
        use_edit = (
            prepared["human_decision"].fillna("").astype(str).str.lower().isin({"send", "edit"})
            & prepared["edited_line"].fillna("").astype(str).str.strip().ne("")
        )
        prepared.loc[use_edit, "personalized_line"] = prepared.loc[use_edit, "edited_line"]
    if "person" in prepared:
        names = prepared["person"].fillna("").astype(str).apply(_split_name)
        prepared["first_name"] = names.apply(lambda pair: pair[0])
        prepared["last_name"] = names.apply(lambda pair: pair[1])
    else:
        prepared["first_name"] = ""
        prepared["last_name"] = ""
    return prepared


def sending_tool_dataframe(df: pd.DataFrame, preset: str = "generic") -> pd.DataFrame:
    preset = preset if preset in SENDING_TOOL_PRESETS else "generic"
    prepared = _prepared_delivery_df(df)
    mapping = SENDING_TOOL_PRESETS[preset]
    output = pd.DataFrame(index=prepared.index)
    for target_column, source_column in mapping.items():
        output[target_column] = _series(prepared, source_column)
    return output.fillna("")
