from __future__ import annotations

from dataclasses import dataclass, field

ATM_PER_BAR = 0.9869232667160128
ATM_PER_KPA = 1 / 101.325


@dataclass(frozen=True)
class Pick:
    date: str | None = None
    o2: tuple[tuple[str, float], ...] = ()
    airflow: tuple[str, ...] = ()
    pressure: tuple[str, ...] = ()
    fuel: str | None = None


@dataclass(frozen=True)
class FileSpec:
    path: str
    pick: Pick
    # Canonical row metric -> (source column, scale). Only used by row-level tools.
    canonical: dict[str, tuple[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class CountRule:
    column: str
    value: str


@dataclass(frozen=True)
class InvestigationAdapter:
    id: str
    files: tuple[FileSpec, ...]
    variables: tuple[str, ...]
    test_label: str = "tests"
    pressure_unit: str = "atm"
    o2_partial: bool = False
    planned_only: bool = False
    count_rule: CountRule | None = None


CANONICAL_ORDER = (
    "bass",
    "bass2",
    "bre",
    "cfi",
    "cfig",
    "cld",
    "efield",
    "flex",
    "flex2",
    "flamedesign",
    "saffire",
    "same",
    "samer",
    "sflame",
    "spice",
)

ADAPTERS: dict[str, InvestigationAdapter] = {
    "bass": InvestigationAdapter(
        id="bass",
        files=(
            FileSpec(
                "bass/BASS_clean.csv",
                Pick(date="date", fuel="material"),
            ),
        ),
        variables=("material", "form", "size_cm", "config", "material_class"),
    ),
    "bass2": InvestigationAdapter(
        id="bass2",
        files=(
            FileSpec(
                "bass2/BASS-II_clean.csv",
                Pick(
                    date="date",
                    o2=(("o2_initial_pct", 1.0),),
                    airflow=("air_cm_s_min", "air_cm_s_max"),
                    fuel="material",
                ),
                canonical={
                    "o2_pct": ("o2_initial_pct", 1.0),
                    "airflow_cm_s": ("air_cm_s_min", 1.0),
                },
            ),
        ),
        variables=(
            "material",
            "geometry",
            "thickness_mm",
            "size_cm",
            "air_cm_s_min",
            "air_cm_s_max",
            "o2_initial_pct",
        ),
    ),
    "bre": InvestigationAdapter(
        id="bre",
        files=(
            FileSpec(
                "bre/BRE_clean.csv",
                Pick(date="date", o2=(("o2_min", 1.0), ("o2_max", 1.0)), fuel="fuel"),
                canonical={"o2_pct": ("o2_min", 1.0)},
            ),
        ),
        variables=("burner_size_mm", "fuel_pct", "o2_levels", "flames_ignited"),
        test_label="test days",
    ),
    "cfi": InvestigationAdapter(
        id="cfi",
        files=(
            FileSpec(
                "cfi/CFI_clean.csv",
                Pick(
                    date="date",
                    o2=(("x_o2", 100.0),),
                    pressure=("p_atm",),
                    fuel="fuel_raw",
                ),
                canonical={
                    "o2_pct": ("x_o2", 100.0),
                    "pressure_atm": ("p_atm", 1.0),
                },
            ),
        ),
        variables=("p_atm", "x_o2", "x_he", "fiber", "fuel_is_blend", "same_condition_count"),
    ),
    "cfig": InvestigationAdapter(
        id="cfig",
        files=(
            FileSpec(
                "cfig/cfi-g_normal_clean.csv",
                Pick(
                    o2=(("o2_before_test", 100.0),),
                    pressure=("pressure_bar",),
                    fuel="fuel",
                ),
                canonical={
                    "o2_pct": ("o2_before_test", 100.0),
                    "pressure_atm": ("pressure_bar", ATM_PER_BAR),
                },
            ),
            FileSpec(
                "cfig/cfi-g_inverse_clean.csv",
                Pick(
                    o2=(("o2_mole_fraction", 100.0),),
                    pressure=("pressure_bar",),
                    fuel="fuel",
                ),
                canonical={
                    "o2_pct": ("o2_mole_fraction", 100.0),
                    "pressure_atm": ("pressure_bar", ATM_PER_BAR),
                },
            ),
        ),
        variables=("o2_before_test", "pressure_bar", "fuel", "burn_time_s", "outcome", "cool_flame"),
        pressure_unit="bar",
    ),
    "cld": InvestigationAdapter(
        id="cld",
        files=(
            FileSpec(
                "cld/cld_flame_clean.csv",
                Pick(date="date", fuel="fuel_species"),
            ),
        ),
        variables=("fuel_species", "bottle_fuel_pct", "conc_min_pct", "conc_max_pct", "flames_ignited"),
        test_label="test days",
    ),
    "efield": InvestigationAdapter(
        id="efield",
        files=(
            FileSpec(
                "efield/efield_clean.csv",
                Pick(date="test_date", fuel="fuel_name"),
            ),
        ),
        variables=("burner_type", "mesh_polarity", "bottle_fuel_pct", "conc_levels_pct", "flames_ignited"),
        test_label="test days",
    ),
    "flamedesign": InvestigationAdapter(
        id="flamedesign",
        files=(
            FileSpec(
                "flamedesign/flame_design_normal_clean.csv",
                Pick(
                    date="date",
                    o2=(("x_o2_init", 100.0),),
                    pressure=("p_mean_ref_atm",),
                    fuel="fuel",
                ),
                canonical={
                    "o2_pct": ("x_o2_init", 100.0),
                    "pressure_atm": ("p_mean_ref_atm", 1.0),
                },
            ),
            FileSpec(
                "flamedesign/flame_design_inverse_clean.csv",
                Pick(
                    date="date",
                    o2=(("x_o2_burner", 100.0),),
                    pressure=("p_mean_atm",),
                    fuel="fuel",
                ),
                canonical={
                    "o2_pct": ("x_o2_burner", 100.0),
                    "pressure_atm": ("p_mean_atm", 1.0),
                },
            ),
        ),
        variables=(
            "flame_type",
            "test_type",
            "x_o2",
            "p_mean_atm",
            "z_st_mean",
            "t_ad_k",
            "same_condition_count",
        ),
    ),
    "flex": InvestigationAdapter(
        id="flex",
        files=(
            FileSpec(
                "flex/FLEX_clean.csv",
                Pick(
                    date="date",
                    o2=(("o2_percent", 1.0),),
                    pressure=("pressure_kpa",),
                    fuel="fuel",
                ),
                canonical={
                    "o2_pct": ("o2_percent", 1.0),
                    "pressure_atm": ("pressure_kpa", ATM_PER_KPA),
                },
            ),
        ),
        variables=("fuel", "o2_percent", "pressure_kpa", "diluent_frac", "d0_mm", "burn_rate", "extinguished"),
        pressure_unit="kPa",
    ),
    "flex2": InvestigationAdapter(
        id="flex2",
        files=(
            FileSpec(
                "flex2/FLEX2_clean.csv",
                Pick(
                    o2=(("o2_mole_fraction_min", 100.0), ("o2_mole_fraction_max", 100.0)),
                    airflow=("flow_velocity_cm_s_min", "flow_velocity_cm_s_max"),
                    pressure=("pressure_atm_min", "pressure_atm_max"),
                    fuel="fuel_raw",
                ),
                canonical={
                    "o2_pct": ("o2_mole_fraction_min", 100.0),
                    "airflow_cm_s": ("flow_velocity_cm_s_min", 1.0),
                    "pressure_atm": ("pressure_atm_min", 1.0),
                },
            ),
        ),
        variables=(
            "droplet_diameter_mm_min",
            "droplet_diameter_mm_max",
            "flow_velocity_cm_s_min",
            "flow_velocity_cm_s_max",
            "o2_mole_fraction_levels",
            "pressure_atm_levels",
            "data_kind",
        ),
        test_label="planned fuel cases",
        planned_only=True,
    ),
    "saffire": InvestigationAdapter(
        id="saffire",
        files=(
            FileSpec(
                "saffire/SAFFIRE-I_clean.csv",
                Pick(
                    date="burn_date",
                    o2=(("o2_percent_min", 1.0), ("o2_percent_max", 1.0)),
                    airflow=("air_flow_cms",),
                    fuel="material",
                ),
                canonical={
                    "o2_pct": ("o2_percent_min", 1.0),
                    "airflow_cm_s": ("air_flow_cms", 1.0),
                },
            ),
        ),
        variables=(
            "material",
            "flow_direction",
            "air_flow_cms",
            "o2_percent_min",
            "o2_percent_max",
            "burn_time_s",
            "length_cm",
            "width_cm",
        ),
        test_label="burns",
        o2_partial=True,
        count_rule=CountRule("record_type", "burn"),
    ),
    "same": InvestigationAdapter(
        id="same",
        files=(
            FileSpec(
                "same/SAME_clean.csv",
                Pick(airflow=("air_flow_cms",), fuel="material"),
                canonical={"airflow_cm_s": ("air_flow_cms", 1.0)},
            ),
        ),
        variables=("material", "air_flow_cms", "weight_loss_rate_mg_min", "aging_min", "varied_factor"),
    ),
    "samer": InvestigationAdapter(
        id="samer",
        files=(
            FileSpec(
                "samer/SAME-R_clean.csv",
                Pick(airflow=("inlet_velocity_cms",), fuel="material"),
                canonical={"airflow_cm_s": ("inlet_velocity_cms", 1.0)},
            ),
        ),
        variables=(
            "material",
            "inlet_velocity_cms",
            "temp_class",
            "is_aging_run",
            "rt_r0",
            "duration_s",
            "net_aging_min",
        ),
    ),
    "sflame": InvestigationAdapter(
        id="sflame",
        files=(
            FileSpec(
                "sflame/sflame_clean.csv",
                Pick(
                    date="test_date",
                    o2=(("o2_min_pct", 1.0), ("o2_max_pct", 1.0)),
                    fuel="fuel_list",
                ),
                canonical={"o2_pct": ("o2_min_pct", 1.0)},
            ),
        ),
        variables=("round_diluent", "o2_levels_pct", "fuel_list", "bottle_inert_pct", "flames_ignited"),
        test_label="test days",
    ),
    "spice": InvestigationAdapter(
        id="spice",
        files=(
            FileSpec(
                "spice/SPICE_clean.csv",
                Pick(date="date", airflow=("air_rate_cm_s",), fuel="fuel_label"),
                canonical={"airflow_cm_s": ("air_rate_cm_s", 1.0)},
            ),
        ),
        variables=("fuel_label", "nozzle_mm", "air_rate_cm_s", "burn_duration_s", "ignition_status"),
        test_label="analysed flames",
        count_rule=CountRule("is_analysis_row", "True"),
    ),
}


METRIC_DEFS = (
    {
        "name": "o2_pct",
        "unit": "%",
        "kind": "range",
        "min": 0,
        "max": 100,
    },
    {
        "name": "pressure_atm",
        "unit": "atm",
        "kind": "range",
        "min": 0,
        "max": None,
    },
    {
        "name": "airflow_cm_s",
        "unit": "cm/s",
        "kind": "range",
        "min": 0,
        "max": None,
    },
    {
        "name": "test_count",
        "unit": "count",
        "kind": "scalar",
        "min": 0,
        "max": None,
    },
    {
        "name": "test_date",
        "unit": "ISO-8601 date",
        "kind": "date",
        "min": None,
        "max": None,
    },
    {
        "name": "fuel",
        "unit": "text",
        "kind": "text",
        "min": None,
        "max": None,
    },
)

METRIC_NAMES = tuple(metric["name"] for metric in METRIC_DEFS)


def adapter_ids() -> tuple[str, ...]:
    return tuple(ADAPTERS)
