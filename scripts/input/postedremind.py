# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de
"""Helper for individual POSTED queries from embedded Python code in GAMS.

POSTED (https://github.com/PhilippVerpoort/posted), the Potsdam open-source
techno-economic database, provides techno-economic values for energy and
climate-mitigation technologies. At every spot in REMIND where such a value is
needed (see core/datainput.gms for examples), an embedded Python code block
chooses the technology, subtechnology, period and units directly at that spot
and calls get_value() once per value. If a value cannot be delivered, the
query raises and the GAMS run fails explicitly, there is no silent fallback
to core/input/generisdata_tech.prn.

get_value() applies the POSTED normalise/select workflow (units are harmonised
across sources, the period is interpolated between data points) and reports
the median across all remaining sources, which keeps individual GAMS values
traceable to a small, logged set of literature sources. Datasets are loaded
and cached once per GAMS run, so many queries cost little time.

The Python packages `posted`, `cet-units` and their dependencies live in
config/pylibs, because the interpreter of the GAMS Embedded Code Facility is
the GMSPython shipped with GAMS; see config/py_requirements.txt for how to
(re)create it. Every applied value is appended to config/posted-values.log
for archiving and reproducibility.
"""

import datetime
import os
import statistics
import sys
import warnings

# Cache loaded POSTED datasets across embedded code blocks within one GAMS run.
_tedf_cache = {}
_logged_header = False


def _add_pylibs_to_path():
    """Make config/pylibs importable."""
    pylibs = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "pylibs"
    )
    if os.path.isdir(pylibs) and pylibs not in sys.path:
        sys.path.insert(0, pylibs)


_add_pylibs_to_path()


def get_value(technology, variable, subtech=None, period=2025, target_unit=""):
    """Return one value from POSTED, converted to target_unit.

    Parameters (as used at the call site in the embedded code blocks):
    technology   POSTED parent variable, e.g. "Tech|Electrolysis"
    variable     POSTED variable, e.g. "CAPEX" or "Output|Hydrogen"
    subtech      list of subtechnology codes to keep, None keeps all
    period       year to query, POSTED interpolates between data points
    target_unit  unit expression the result is converted to, interpreted by
                 cet-units with POSTED's flow definitions active, e.g.
                 "USD_2015 / kW" or "kWh_H2_LHV / kWh" or "year"

    Raises an exception when the value cannot be determined, which makes the
    GAMS Embedded Code Facility fail the run explicitly.
    """
    from cet_units import ureg

    if technology not in _tedf_cache:
        import posted

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _tedf_cache[technology] = posted.TEDF.load(technology)
    tedf = _tedf_cache[technology]

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
            f"no POSTED rows for variable '{variable}' in '{technology}'"
            + (f", subtech {list(subtech)}" if subtech else "")
            + f", period {period}"
        )

    values = []
    for row in rows.itertuples():
        reference = row.reference_unit
        # Empty or missing reference_unit means the value stands alone.
        divisor = (
            f"({reference})"
            if isinstance(reference, str) and reference
            else "1"
        )
        quantity = ureg(f"{row.value} * ({row.unit}) / {divisor}")
        values.append(quantity.to(target_unit).m)
    return statistics.median(values)


def log(message):
    """Append one audit line to config/posted-values.log."""
    global _logged_header
    logfile = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "config",
        "posted-values.log",
    )
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(logfile, "a", encoding="utf-8") as logfile:
        if not _logged_header:
            from importlib.metadata import version

            logfile.write(
                f"{stamp} POSTED v{version('posted')} values fetched"
                " by embedded Python code during GAMS run\n"
            )
            _logged_header = True
        logfile.write(f"{stamp} {message}\n")
