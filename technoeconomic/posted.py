# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de
"""Fetch techno-economic data for REMIND from POSTED.

POSTED (https://github.com/PhilippVerpoort/posted), the Potsdam open-source
techno-economic database, provides techno-economic values for energy and
climate-mitigation technologies. This script queries the POSTED TEDFs listed
in QUERIES below and writes every fetched value, as the median across all
sources and subtechnologies, into technoeconomic/technoeconomic-raw.csv with
columns property;tech;year;region;value;unit.

No regional aggregation happens here. POSTED currently provides global data,
which is written with region "global". The regional resolution to REMIND
regions and the copy into core/input/technoeconomic.csv, from where
core/datainput.gms reads it into p_technoeconomic, are done by
scripts/input/create_input_for_technoeconomic.R using madrat region mappings.

The POSTED commit used is pinned in config/py_requirements.txt and recorded
in cfg$postedVersion (config/default.cfg). Run this script with the REMIND
conda environment (make create-conda), e.g. from the REMIND main folder:

    python technoeconomic/posted.py
"""

import statistics
import sys
import warnings
from pathlib import Path

# technoeconomic/posted.py shadows the posted package if its folder is on
# sys.path, which Python does automatically when running this file directly.
_here = str(Path(__file__).parent.resolve())
sys.path[:] = [p for p in sys.path if str(Path(p or ".").resolve()) != _here]

import pint
from posted import TEDF, defaults

# Harmonise monetary values to US dollars of 2017 instead of POSTED's default.
defaults["currency"] = "USD_2017"

# Import cet-units after posted was imported, so POSTED's flow definitions
# (H2, NG, ...) are active in the unit registry used for the conversions.
from cet_units import ureg

# Years to fetch. POSTED interpolates between its data points and
# extrapolates outside their range, so the year of a query need not coincide
# with years present in the TEDF csv files.
PERIODS = [2020, 2025, 2030, 2040, 2050]

# QUERIES: REMIND technology -> TEDF parent variable, subtechnologies to
# average over, and REMIND properties to fetch. A property is defined by the
# POSTED variable and the unit the value is converted to. divide_by refers to
# another property of the same technology whose value is divided out.
QUERIES = {
    "elh2": {
        "tedf": "Tech|Electrolysis",
        "subtech": ["AEL", "PEM"],
        "properties": {
            # CAPEX per kW electricity, divided by the efficiency to arrive
            # at USD_2017 per kW(H2) like in generisdata_tech.prn.
            "inco0": {"variable": "CAPEX", "unit": "USD_2017 / kW",
                      "divide_by": "eta"},
            "eta": {"variable": "Output|Hydrogen",
                    "unit": "kWh_H2_LHV / kWh"},
        },
    },
    "ngcc": {
        "tedf": "Tech|Gas Turbine",
        "subtech": ["CCGT conventional"],
        "properties": {
            "inco0": {"variable": "CAPEX", "unit": "USD_2017 / kW"},
            # POSTED gives the specific natural gas input per kWh of
            # electricity, converting to the inverted unit yields the
            # efficiency directly.
            "eta": {"variable": "Input|Natural Gas",
                    "unit": "kWh / kWh_NG_LHV"},
        },
    },
    "h2turb": {
        "tedf": "Tech|Gas Turbine",
        "subtech": ["CCGT H2-ready"],
        "properties": {
            "inco0": {"variable": "CAPEX", "unit": "USD_2017 / kW"},
            "eta": {"variable": "Input|Hydrogen",
                    "unit": "kWh / kWh_H2_LHV"},
        },
    },
}


def get_values(tedf, subtech, period, variable, unit):
    """Return {region: median value} for one property at one period.

    Applies the POSTED normalise/select workflow (units harmonised across
    sources, the period interpolated between data points) and reports, per
    region, the median across all remaining rows, converting each value to
    the given target unit. Raises if no rows match the query.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        selected = tedf.select(
            **({"subtech": list(subtech)} if subtech else {}),
            period=[period],
            drop_singular_fields=False,
        )
    rows = selected[selected["variable"] == variable]
    if rows.empty:
        raise LookupError(
            f"no POSTED rows for variable '{variable}'"
            + (f", subtech {list(subtech)}" if subtech else "")
            + f", period {period}"
        )
    if "region" not in rows.columns:
        # POSTED TEDFs without a region field contain global data only.
        rows = rows.assign(region="global")

    target = ureg(unit)
    values = {}
    for row in rows.itertuples():
        reference = row.reference_unit
        # Empty or missing reference_unit means the value stands alone.
        divisor = (
            f"({reference})"
            if isinstance(reference, str) and reference
            else "1"
        )
        quantity = ureg(f"{row.value} * ({row.unit}) / {divisor}")
        if quantity.dimensionality == target.dimensionality:
            converted = quantity.to(target).m
        else:
            # POSTED variables like Input|Natural Gas are inverses of
            # properties like efficiency. Rows with a zero input value have
            # no finite inverse and are skipped.
            try:
                converted = (1 / quantity).to(target).m
            except ZeroDivisionError:
                continue
            except pint.DimensionalityError as exc:
                raise pint.DimensionalityError(
                    quantity.units, target, extra_msg=f" for row {row.Index}"
                ) from exc
        values.setdefault(row.region, []).append(converted)
    if not values:
        raise LookupError(
            f"no POSTED rows for variable '{variable}' convertible to "
            f"'{unit}' for period {period}"
        )
    return {
        region: statistics.median(regionvalues)
        for region, regionvalues in values.items()
    }


def main():
    outfile = Path(__file__).parent / "technoeconomic-raw.csv"
    lines = ["property;tech;year;region;value;unit"]
    tedfs = {}
    for tech, query in QUERIES.items():
        if query["tedf"] not in tedfs:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tedfs[query["tedf"]] = TEDF.load(query["tedf"])
        tedf = tedfs[query["tedf"]]
        for period in PERIODS:
            # Simple properties first, so derived ones can divide them out.
            properties = sorted(
                query["properties"],
                key=lambda prop: "divide_by" in query["properties"][prop],
            )
            fetched = {}
            for prop in properties:
                spec = query["properties"][prop]
                values = get_values(
                    tedf,
                    query["subtech"],
                    period,
                    spec["variable"],
                    spec["unit"],
                )
                if "divide_by" in spec:
                    divider = fetched[spec["divide_by"]]
                    values = {
                        region: value / divider[region]
                        for region, value in values.items()
                    }
                fetched[prop] = values
                for region, value in sorted(values.items()):
                    lines.append(
                        f"{prop};{tech};{period};{region};{value:.6g};"
                        f"{spec['unit']}"
                    )
                    print(
                        f"{tech},{prop} {period} {region}: {value:.6g} "
                        f"{spec['unit']} (POSTED {query['tedf']} "
                        f"{spec['variable']})"
                    )
    outfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines) - 1} values to {outfile}")


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        sys.exit("technoeconomic/posted.py requires Python 3.10 or newer.")
    main()
