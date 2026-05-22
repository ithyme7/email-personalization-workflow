from __future__ import annotations

import hashlib
import logging
import math
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExperimentVariant:
    """Een variant binnen een A/B-test."""
    variant_id: str          # Bijv. "control", "variant_b", "variant_c"
    label: str               # Mens-leesbare label
    description: str = ""    # Wat is anders aan deze variant


@dataclass
class ExperimentConfig:
    """Definitie van een A/B-test-experiment."""
    experiment_id: str
    name: str
    variants: list[ExperimentVariant]
    allocation_strategy: str = "thompson"  # "random" | "thompson" | "fixed"
    fixed_weights: dict[str, float] = field(default_factory=dict)  # variant_id → weight
    min_sample_size: int = 30            # Minimaal per variant voordat we evalueren
    significance_level: float = 0.05     # p-waarde drempel
    max_total: int = 0                   # 0 = geen limiet
    enabled: bool = True


@dataclass
class ExperimentAssignment:
    """Resultaat van toewijzing van een lead aan een variant."""
    experiment_id: str
    variant_id: str
    variant_label: str
    lead_hash: str


@dataclass
class VariantResult:
    """Geaggregeerde resultaten voor één variant."""
    variant_id: str
    total: int = 0
    opened: int = 0
    replied: int = 0
    converted: int = 0

    @property
    def open_rate(self) -> float:
        return self.opened / self.total if self.total else 0.0

    @property
    def reply_rate(self) -> float:
        return self.replied / self.total if self.total else 0.0

    @property
    def conversion_rate(self) -> float:
        return self.converted / self.total if self.total else 0.0


@dataclass
class ExperimentReport:
    """Rapportage voor een volledig experiment."""
    experiment_id: str
    experiment_name: str
    total_leads: int
    status: str  # "running" | "significant" | "inconclusive" | "stopped"
    winner_variant_id: str | None
    variants: list[dict[str, Any]]
    is_significant: bool
    p_value: float | None
    confidence_intervals: list[dict[str, Any]]
    recommendation: str


# ---------------------------------------------------------------------------
# Statistische hulpfuncties
# ---------------------------------------------------------------------------

def _chi_squared_test(
    successes_a: int, total_a: int,
    successes_b: int, total_b: int,
) -> float:
    """
    Chi-kwadraad test voor twee proporties.
    Retourneert de p-waarde (benaderd via normale verdeling voor grote steekproeven).
    Gebruikt Yates' correctie voor kleine steekproeven.
    """
    if total_a == 0 or total_b == 0:
        return 1.0

    # Pooled proportion
    total_success = successes_a + successes_b
    total_n = total_a + total_b
    p_pool = total_success / total_n if total_n else 0.5

    if p_pool == 0 or p_pool == 1:
        return 1.0

    # Expected values
    exp_a = total_a * p_pool
    exp_b = total_b * p_pool
    exp_fail_a = total_a * (1 - p_pool)
    exp_fail_b = total_b * (1 - p_pool)

    # Yates' correction
    def _yates(obs, exp):
        diff = abs(obs - exp) - 0.5
        return max(diff, 0) ** 2 / exp if exp > 0 else 0

    chi2 = (
        _yates(successes_a, exp_a) +
        _yates(successes_b, exp_b) +
        _yates(total_a - successes_a, exp_fail_a) +
        _yates(total_b - successes_b, exp_fail_b)
    )

    # p-waarde benadering (chi2 met 1 df → standaardnormaal)
    # Gebruik Wilson-Hilferty benadering
    if chi2 <= 0:
        return 1.0

    z = math.sqrt(chi2)
    # Standaardnormale CDF benadering (Abramowitz & Stegun)
    p_value = _normal_cdf(-abs(z))
    return min(max(p_value, 0.0), 1.0)


def _normal_cdf(x: float) -> float:
    """Benadering van de standaardnormale CDF."""
    if x < -8:
        return 0.0
    if x > 8:
        return 1.0
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2.0)
    return 0.5 * (1.0 + sign * y)


def _proportion_ci(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval voor een proportie."""
    if total == 0:
        return (0.0, 0.0)
    p_hat = successes / total
    denom = 1 + z ** 2 / total
    centre = (p_hat + z ** 2 / (2 * total)) / denom
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * total)) / total) / denom
    return (max(0, centre - spread), min(1, centre + spread))


# ---------------------------------------------------------------------------
# Thompson Sampling
# ---------------------------------------------------------------------------

class ThompsonSampler:
    """
    Thompson Sampling multi-armed bandit voor adaptieve variant-allocatie.
    Modelleert elke variant als een Beta(alpha, beta) verdeling.
    """

    def __init__(self, variant_ids: list[str]):
        # Prior: Beta(1, 1) = uniform
        self.priors: dict[str, tuple[float, float]] = {
            vid: (1.0, 1.0) for vid in variant_ids
        }

    def sample(self) -> str:
        """Trek één sample per variant, retourneer de variant met hoogste waarde."""
        samples = {
            vid: random.betavariate(alpha, beta)
            for vid, (alpha, beta) in self.priors.items()
        }
        return max(samples, key=samples.get)

    def update(self, variant_id: str, success: bool) -> None:
        """Update de posterior na een observatie."""
        alpha, beta = self.priors[variant_id]
        if success:
            self.priors[variant_id] = (alpha + 1, beta)
        else:
            self.priors[variant_id] = (alpha, beta + 1)

    def update_batch(self, variant_id: str, successes: int, failures: int) -> None:
        """Batch-update na meerdere observaties."""
        alpha, beta = self.priors[variant_id]
        self.priors[variant_id] = (alpha + successes, beta + failures)

    def get_stats(self) -> dict[str, dict[str, float]]:
        """Retourneer huidige posteriors en verwachte waarden."""
        result = {}
        for vid, (alpha, beta) in self.priors.items():
            total = alpha + beta
            result[vid] = {
                "alpha": alpha,
                "beta": beta,
                "mean": alpha / total if total > 0 else 0.5,
                "samples": total - 2,  # aftrekken van prior
            }
        return result


# ---------------------------------------------------------------------------
# Database: experiment tracking
# ---------------------------------------------------------------------------

EXPERIMENT_DB = DATA_DIR / "experiments.sqlite3"


def _exp_connect() -> sqlite3.Connection:
    EXPERIMENT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(EXPERIMENT_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_experiment_db() -> None:
    """Maak tabellen aan als ze nog niet bestaan."""
    conn = _exp_connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                variants_json TEXT NOT NULL,
                allocation_strategy TEXT DEFAULT 'thompson',
                min_sample_size INTEGER DEFAULT 30,
                significance_level REAL DEFAULT 0.05,
                max_total INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiment_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                variant_id TEXT NOT NULL,
                variant_label TEXT,
                lead_hash TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                UNIQUE(experiment_id, lead_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_exp_assign_lead
            ON experiment_assignments(experiment_id, lead_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiment_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                variant_id TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                was_opened INTEGER DEFAULT 0,
                got_reply INTEGER DEFAULT 0,
                converted INTEGER DEFAULT 0,
                recorded_at TEXT NOT NULL,
                UNIQUE(experiment_id, variant_id, lead_id)
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Experiment management
# ---------------------------------------------------------------------------

def register_experiment(config: ExperimentConfig) -> bool:
    """Registreer een nieuw experiment. Retourneert True als succesvol."""
    init_experiment_db()
    conn = _exp_connect()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        import json
        conn.execute("""
            INSERT OR REPLACE INTO experiments
            (experiment_id, name, variants_json, allocation_strategy,
             min_sample_size, significance_level, max_total, enabled,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            config.experiment_id,
            config.name,
            json.dumps([v.__dict__ for v in config.variants]),
            config.allocation_strategy,
            config.min_sample_size,
            config.significance_level,
            config.max_total,
            1 if config.enabled else 0,
            now,
            now,
        ))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def get_experiment(experiment_id: str) -> ExperimentConfig | None:
    """Haal experiment config op."""
    init_experiment_db()
    conn = _exp_connect()
    try:
        row = conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if not row:
            return None
        import json
        variants_data = json.loads(row[2])
        variants = [
            ExperimentVariant(v["variant_id"], v["label"], v.get("description", ""))
            for v in variants_data
        ]
        return ExperimentConfig(
            experiment_id=row[0],
            name=row[1],
            variants=variants,
            allocation_strategy=row[3],
            fixed_weights={},  # Kan later worden opgehaald
            min_sample_size=row[4],
            significance_level=row[5],
            max_total=row[6],
            enabled=bool(row[7]),
        )
    finally:
        conn.close()


def list_active_experiments() -> list[ExperimentConfig]:
    """Lijst van alle actieve experimenten."""
    init_experiment_db()
    conn = _exp_connect()
    try:
        rows = conn.execute(
            "SELECT experiment_id FROM experiments WHERE enabled = 1"
        ).fetchall()
        experiments = []
        for row in rows:
            exp = get_experiment(row[0])
            if exp:
                experiments.append(exp)
        return experiments
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Assignment: bepaal welke variant een lead krijgt
# ---------------------------------------------------------------------------

def assign_lead_to_variant(
    experiment_id: str,
    lead_id: str,
    variants: list[ExperimentVariant],
    strategy: str = "thompson",
    fixed_weights: dict[str, float] | None = None,
) -> ExperimentAssignment | None:
    """
    Wijs een lead toe aan een variant.
    Deterministisch op basis van lead_hash (zelfde lead → zelfde variant).

    Returns None als geen actieve experimenten.
    """
    from config import load_settings
    settings = load_settings()

    if not settings.ab_testing_enabled:
        return None

    init_experiment_db()
    conn = _exp_connect()

    # Check of lead al toegewezen is
    existing = conn.execute(
        "SELECT variant_id, variant_label FROM experiment_assignments "
        "WHERE experiment_id = ? AND lead_id = ?",
        (experiment_id, lead_id),
    ).fetchone()
    if existing:
        return ExperimentAssignment(
            experiment_id=experiment_id,
            variant_id=existing[0],
            variant_label=existing[1] or "",
            lead_hash=_hash_lead(experiment_id, lead_id),
        )

    # Bepaal variant
    variant_id = _determine_variant(
        strategy=strategy,
        variants=variants,
        fixed_weights=fixed_weights or {},
        experiment_id=experiment_id,
        lead_id=lead_id,
    )

    if variant_id is None:
        return None

    variant_label = next(
        (v.label for v in variants if v.variant_id == variant_id),
        variant_id,
    )
    lead_hash = _hash_lead(experiment_id, lead_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """INSERT INTO experiment_assignments
           (experiment_id, lead_id, variant_id, variant_label, lead_hash, assigned_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (experiment_id, lead_id, variant_id, variant_label, lead_hash, now),
    )
    conn.commit()
    conn.close()

    return ExperimentAssignment(
        experiment_id=experiment_id,
        variant_id=variant_id,
        variant_label=variant_label,
        lead_hash=lead_hash,
    )


def _hash_lead(experiment_id: str, lead_id: str) -> str:
    """Deterministische hash voor reproduceerbare toewijzing."""
    raw = f"{experiment_id}:{lead_id}".encode()
    return hashlib.md5(raw).hexdigest()


def _determine_variant(
    strategy: str,
    variants: list[ExperimentVariant],
    fixed_weights: dict[str, float],
    experiment_id: str,
    lead_id: str,
) -> str | None:
    """Bepaal welke variant te gebruiken op basis van strategie."""
    if strategy == "fixed":
        return _fixed_allocation(fixed_weights, variants)
    elif strategy == "thompson":
        return _thompson_allocation(experiment_id, variants)
    else:
        # Random fallback
        return _random_allocation(variants, experiment_id, lead_id)


def _fixed_allocation(
    weights: dict[str, float],
    variants: list[ExperimentVariant],
) -> str | None:
    """Bepaal variant op basis van vaste gewichten."""
    if not weights:
        return None
    import random
    variant_ids = list(weights.keys())
    w = [weights[vid] for vid in variant_ids]
    return random.choices(variant_ids, weights=w, k=1)[0]


def _thompson_allocation(
    experiment_id: str,
    variants: list[ExperimentVariant],
) -> str:
    """Thompson Sampling: trek uit de posterior van elke variant."""
    init_experiment_db()
    conn = _exp_connect()
    try:
        variant_ids = [v.variant_id for v in variants]
        sampler = ThompsonSampler(variant_ids)

        # Laad huidige resultaten om posteriors te updaten
        for vid in variant_ids:
            rows = conn.execute(
                """SELECT was_opened, got_reply, converted
                   FROM experiment_results
                   WHERE experiment_id = ? AND variant_id = ?""",
                (experiment_id, vid),
            ).fetchall()
            if not rows:
                continue
            total_success = sum(r[2] for r in rows)  # conversions
            total_fail = len(rows) - total_success
            if total_success > 0 or total_fail > 0:
                sampler.update_batch(vid, total_success, total_fail)

        return sampler.sample()
    finally:
        conn.close()


def _random_allocation(
    variants: list[ExperimentVariant],
    experiment_id: str,
    lead_id: str,
) -> str:
    """Random toewijzing, deterministisch op basis van hash."""
    h = _hash_lead(experiment_id, lead_id)
    idx = int(h[:8], 16) % len(variants)
    return variants[idx].variant_id


# ---------------------------------------------------------------------------
# Results: track experiment outcomes
# ---------------------------------------------------------------------------

def record_experiment_result(
    experiment_id: str,
    variant_id: str,
    lead_id: str,
    was_opened: bool = False,
    got_reply: bool = False,
    converted: bool = False,
) -> bool:
    """Sla resultaat van een experimenteel verstuurde email op."""
    init_experiment_db()
    conn = _exp_connect()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute("""
            INSERT OR REPLACE INTO experiment_results
            (experiment_id, variant_id, lead_id, was_opened, got_reply, converted, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (experiment_id, variant_id, lead_id,
              1 if was_opened else 0,
              1 if got_reply else 0,
              1 if converted else 0,
              now))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def get_variant_results(experiment_id: str) -> list[VariantResult]:
    """Haal geaggregeerde resultaten per variant op."""
    init_experiment_db()
    conn = _exp_connect()
    try:
        rows = conn.execute(
            """SELECT variant_id,
                      COUNT(*) as total,
                      SUM(was_opened) as opened,
                      SUM(got_reply) as replied,
                      SUM(converted) as converted
               FROM experiment_results
               WHERE experiment_id = ?
               GROUP BY variant_id
            """,
            (experiment_id,),
        ).fetchall()
        return [
            VariantResult(
                variant_id=r[0],
                total=r[1],
                opened=r[2] or 0,
                replied=r[3] or 0,
                converted=r[4] or 0,
            )
            for r in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analysis: statistische significantie
# ---------------------------------------------------------------------------

def analyze_experiment(experiment_id: str) -> ExperimentReport:
    """
    Analyseer een volledig experiment.
    Voert pairwise chi-kwadraad testen uit tussen control en elke variant.
    """
    config = get_experiment(experiment_id)
    if not config:
        raise ValueError(f"Experiment '{experiment_id}' niet gevonden")

    variant_results = get_variant_results(experiment_id)

    if len(variant_results) < 2:
        return ExperimentReport(
            experiment_id=config.experiment_id,
            experiment_name=config.name,
            total_leads=sum(v.total for v in variant_results),
            status="running",
            winner_variant_id=None,
            variants=[],
            is_significant=False,
            p_value=None,
            confidence_intervals=[],
            recommendation="Nog onvoldoende data — wacht tot minstens 2 varianten resultaten hebben.",
        )

    variant_analyses = []
    control = variant_results[0]
    min_sample = config.min_sample_size

    for vr in variant_results:
        enough_data = vr.total >= min_sample
        if vr.variant_id == control.variant_id:
            # Control variant — vergelijk met andere varianten
            p_value = None
            is_winner = False
        else:
            # Test tegen control
            if control.total >= min_sample and vr.total >= min_sample:
                p_value = _chi_squared_test(
                    control.converted, control.total,
                    vr.converted, vr.total,
                )
                is_winner = p_value < config.significance_level and vr.conversion_rate > control.conversion_rate
            else:
                p_value = None
                is_winner = False

        ci_low, ci_high = _proportion_ci(vr.converted, vr.total)

        variant_analyses.append({
            "variant_id": vr.variant_id,
            "label": next(
                (v.label for v in config.variants if v.variant_id == vr.variant_id),
                vr.variant_id,
            ),
            "total": vr.total,
            "opened": vr.opened,
            "replied": vr.replied,
            "converted": vr.converted,
            "open_rate": round(vr.open_rate * 100, 1),
            "reply_rate": round(vr.reply_rate * 100, 1),
            "conversion_rate": round(vr.conversion_rate * 100, 1),
            "ci_low": round(ci_low * 100, 1),
            "ci_high": round(ci_high * 100, 1),
            "p_value": round(p_value, 4) if p_value is not None else None,
            "significant_winner": is_winner,
            "enough_data": enough_data,
        })

    # Bepaal winnaar
    significant_winners = [
        v for v in variant_analyses
        if v["significant_winner"]
    ]
    all_sufficient = all(v["enough_data"] for v in variant_analyses)

    if significant_winners:
        winner = max(significant_winners, key=lambda v: v["conversion_rate"])
        status = "significant"
        recommendation = (
            f"WINNAAR: '{winner['label']}' met {winner['conversion_rate']}% "
            f"conversie (p={winner['p_value']}). Schaal deze variant op."
        )
    elif all_sufficient:
        winner = max(variant_analyses, key=lambda v: v["conversion_rate"])
        status = "inconclusive"
        recommendation = (
            f"Geen statistisch significant verschil. Beste performer: "
            f"'{winner['label']}' ({winner['conversion_rate']}%), "
            f"maar niet significant. Verzamel meer data of pas varianten aan."
        )
    else:
        winner = max(variant_analyses, key=lambda v: v["conversion_rate"])
        status = "running"
        recommendation = (
            f"Te weinig data — minstens {min_sample} per variant nodig. "
            f"Huidige voorloper: '{winner['label']}' ({winner['conversion_rate']}%)."
        )

    return ExperimentReport(
        experiment_id=config.experiment_id,
        experiment_name=config.name,
        total_leads=sum(v["total"] for v in variant_analyses),
        status=status,
        winner_variant_id=winner["variant_id"] if winner else None,
        variants=variant_analyses,
        is_significant=bool(significant_winners),
        p_value=significant_winners[0]["p_value"] if significant_winners else None,
        confidence_intervals=[
            {"variant_id": v["variant_id"], "ci_low": v["ci_low"], "ci_high": v["ci_high"]}
            for v in variant_analyses
        ],
        recommendation=recommendation,
    )


def print_experiment_report(report: ExperimentReport) -> None:
    """Print een leesbaar experimentrapport naar de console."""
    print(f"\n{'='*60}")
    print(f"  A/B TEST: {report.experiment_name} ({report.experiment_id})")
    print(f"  Status: {report.status.upper()}")
    print(f"  Totaal leads: {report.total_leads}")
    print(f"{'='*60}")

    print(f"\n  {'Variant':<20} {'N':>5} {'Open%':>7} {'Reply%':>8} {'Conv%':>7} {'95% CI':>15} {'p-waarde':>10}")
    print(f"  {'-'*20} {'-'*5} {'-'*7} {'-'*8} {'-'*7} {'-'*15} {'-'*10}")

    for v in report.variants:
        ci_str = f"[{v['ci_low']}%–{v['ci_high']}%]"
        p_str = f"{v['p_value']:.4f}" if v['p_value'] is not None else "—"
        marker = " ◀ WINNAAR" if v["significant_winner"] else ""
        print(f"  {v['label']:<20} {v['total']:>5} {v['open_rate']:>6.1f}% {v['reply_rate']:>7.1f}% {v['conversion_rate']:>6.1f}% {ci_str:>15} {p_str:>10}{marker}")

    print(f"\n  ▸ Aanbeveling: {report.recommendation}")
    print(f"{'='*60}\n")