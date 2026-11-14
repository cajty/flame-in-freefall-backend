// Per-investigation mapping from cleaned CSV columns to the summary fields shown in the app.
// Every list of summary values is already normalised: O2 in percent, airflow in cm/s, dates as YYYY-MM-DD.

const values = (rows, key) => rows.map((r) => r[key] ?? "").filter((v) => v !== "");

const nums = (rows, keys, scale = 1) =>
  rows
    .flatMap((r) => keys.map((k) => r[k]))
    .filter((v) => v !== "" && v != null)
    .map(Number)
    .filter(Number.isFinite)
    .map((v) => v * scale);

const pick = ({ date, o2 = [], airflow = [], pressure = [], fuel }) => (rows) => ({
  dates: date ? values(rows, date) : [],
  o2: nums(rows, o2),
  airflow: nums(rows, airflow),
  pressure: nums(rows, pressure),
  fuels: fuel ? values(rows, fuel) : [],
});

export const ADAPTERS = {
  bass: {
    files: [{ path: "bass/BASS_clean.csv", pick: pick({ date: "date", fuel: "material" }) }],
    variables: ["material", "form", "size_cm", "config", "material_class"],
  },
  bass2: {
    files: [
      {
        path: "bass2/BASS-II_clean.csv",
        pick: pick({
          date: "date",
          o2: ["o2_initial_pct"],
          airflow: ["air_cm_s_min", "air_cm_s_max"],
          fuel: "material",
        }),
      },
    ],
    variables: ["material", "geometry", "thickness_mm", "size_cm", "air_cm_s_min", "air_cm_s_max", "o2_initial_pct"],
  },
  bre: {
    testLabel: "test days",
    files: [{ path: "bre/BRE_clean.csv", pick: pick({ date: "date", o2: ["o2_min", "o2_max"], fuel: "fuel" }) }],
    variables: ["burner_size_mm", "fuel_pct", "o2_levels", "flames_ignited"],
  },
  cfi: {
    files: [
      {
        path: "cfi/CFI_clean.csv",
        pick: (rows) => ({
          dates: values(rows, "date"),
          o2: nums(rows, ["x_o2"], 100),
          airflow: [],
          pressure: nums(rows, ["p_atm"]),
          fuels: values(rows, "fuel_raw"),
        }),
      },
    ],
    variables: ["p_atm", "x_o2", "x_he", "fiber", "fuel_is_blend", "same_condition_count"],
  },
  cfig: {
    files: [
      {
        path: "cfig/cfi-g_normal_clean.csv",
        pick: (rows) => ({
          dates: [],
          o2: nums(rows, ["o2_before_test"], 100),
          airflow: [],
          pressure: nums(rows, ["pressure_bar"]),
          fuels: values(rows, "fuel"),
        }),
      },
      {
        path: "cfig/cfi-g_inverse_clean.csv",
        pick: (rows) => ({
          dates: [],
          o2: nums(rows, ["o2_mole_fraction"], 100),
          airflow: [],
          pressure: nums(rows, ["pressure_bar"]),
          fuels: values(rows, "fuel"),
        }),
      },
    ],
    pressureUnit: "bar",
    variables: ["o2_before_test", "pressure_bar", "fuel", "burn_time_s", "outcome", "cool_flame"],
  },
  cld: {
    testLabel: "test days",
    files: [{ path: "cld/cld_flame_clean.csv", pick: pick({ date: "date", fuel: "fuel_species" }) }],
    variables: ["fuel_species", "bottle_fuel_pct", "conc_min_pct", "conc_max_pct", "flames_ignited"],
  },
  efield: {
    testLabel: "test days",
    files: [{ path: "efield/efield_clean.csv", pick: pick({ date: "test_date", fuel: "fuel_name" }) }],
    variables: ["burner_type", "mesh_polarity", "bottle_fuel_pct", "conc_levels_pct", "flames_ignited"],
  },
  flamedesign: {
    files: [
      {
        path: "flamedesign/flame_design_normal_clean.csv",
        pick: (rows) => ({
          dates: values(rows, "date"),
          o2: nums(rows, ["x_o2_init"], 100),
          airflow: [],
          pressure: nums(rows, ["p_mean_ref_atm"]),
          fuels: values(rows, "fuel"),
        }),
      },
      {
        path: "flamedesign/flame_design_inverse_clean.csv",
        pick: (rows) => ({
          dates: values(rows, "date"),
          o2: nums(rows, ["x_o2_burner"], 100),
          airflow: [],
          pressure: nums(rows, ["p_mean_atm"]),
          fuels: values(rows, "fuel"),
        }),
      },
    ],
    variables: ["flame_type", "test_type", "x_o2", "p_mean_atm", "z_st_mean", "t_ad_k", "same_condition_count"],
  },
  flex: {
    files: [
      {
        path: "flex/FLEX_clean.csv",
        pick: pick({
          date: "date",
          o2: ["o2_percent"],
          pressure: ["pressure_kpa"],
          fuel: "fuel",
        }),
      },
    ],
    pressureUnit: "kPa",
    variables: ["fuel", "o2_percent", "pressure_kpa", "diluent_frac", "d0_mm", "burn_rate", "extinguished"],
  },
  flex2: {
    testLabel: "planned fuel cases",
    files: [
      {
        path: "flex2/FLEX2_clean.csv",
        pick: (rows) => ({
          dates: [],
          o2: nums(rows, ["o2_mole_fraction_min", "o2_mole_fraction_max"], 100),
          airflow: nums(rows, ["flow_velocity_cm_s_min", "flow_velocity_cm_s_max"]),
          pressure: nums(rows, ["pressure_atm_min", "pressure_atm_max"]),
          fuels: values(rows, "fuel_raw"),
        }),
      },
    ],
    variables: [
      "droplet_diameter_mm_min",
      "droplet_diameter_mm_max",
      "flow_velocity_cm_s_min",
      "flow_velocity_cm_s_max",
      "o2_mole_fraction_levels",
      "pressure_atm_levels",
      "data_kind",
    ],
  },
  saffire: {
    testLabel: "burns",
    count: (rows) => rows.filter((r) => r.record_type === "burn").length,
    files: [
      {
        path: "saffire/SAFFIRE-I_clean.csv",
        pick: pick({
          date: "burn_date",
          o2: ["o2_percent_min", "o2_percent_max"],
          airflow: ["air_flow_cms"],
          fuel: "material",
        }),
      },
    ],
    // Only Saffire-I is in data/processed; the app entry covers Saffire I-III.
    o2Partial: true,
    variables: [
      "material",
      "flow_direction",
      "air_flow_cms",
      "o2_percent_min",
      "o2_percent_max",
      "burn_time_s",
      "length_cm",
      "width_cm",
    ],
  },
  same: {
    files: [{ path: "same/SAME_clean.csv", pick: pick({ airflow: ["air_flow_cms"], fuel: "material" }) }],
    variables: ["material", "air_flow_cms", "weight_loss_rate_mg_min", "aging_min", "varied_factor"],
  },
  samer: {
    files: [{ path: "samer/SAME-R_clean.csv", pick: pick({ airflow: ["inlet_velocity_cms"], fuel: "material" }) }],
    variables: ["material", "inlet_velocity_cms", "temp_class", "is_aging_run", "rt_r0", "duration_s", "net_aging_min"],
  },
  sflame: {
    testLabel: "test days",
    files: [
      {
        path: "sflame/sflame_clean.csv",
        pick: pick({ date: "test_date", o2: ["o2_min_pct", "o2_max_pct"], fuel: "fuel_list" }),
      },
    ],
    variables: ["round_diluent", "o2_levels_pct", "fuel_list", "bottle_inert_pct", "flames_ignited"],
  },
  spice: {
    testLabel: "analysed flames",
    count: (rows) => rows.filter((r) => r.is_analysis_row === "True").length,
    files: [
      {
        path: "spice/SPICE_clean.csv",
        pick: pick({ date: "date", airflow: ["air_rate_cm_s"], fuel: "fuel_label" }),
      },
    ],
    variables: ["fuel_label", "nozzle_mm", "air_rate_cm_s", "burn_duration_s", "ignition_status"],
  },
};
