# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de
"""Write the REMIND input csv file computed from POSTED by content.py.

This is what scripts/input/create_input_for_technoeconomic.R calls, it writes
core/input/f_technoeconomic.csv: one char,te,value line per property, the shape
of fm_dataglob, each of them preceded by a comment naming its unit, which GAMS
ignores inside a data definition. It includes inco0year, the year its inco0
values are from. core/datainput.gms reads it to replace values from
generisdata_tech.prn. The file is committed, its header lines "POSTED version"
and "TEAM version" name the commits of the packages the values are computed
with, and "technoeconomic md5" those scripts; --check compares all of them with
pyproject.toml and these files, and prepare.R and the tests run --check.
Regenerate and commit the csv after changing any of them. An editable install of
one of the packages records its local folder as the version, do not commit such
a file.

Run it via that R script, or directly with the environment that 'uv sync'
creates, from the REMIND main folder:

    python technoeconomic/create_input.py [--out PATH]
    python technoeconomic/create_input.py --check
"""

import argparse
import hashlib
import json
import math
import sys
import tomllib
from importlib import metadata
from pathlib import Path

REMIND_FOLDER = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REMIND_FOLDER / "core" / "input" / "f_technoeconomic.csv"
# the values depend on the queries and on how they are formatted here
SOURCE_FILES = [Path(__file__), Path(__file__).with_name("content.py")]
# the packages the values are computed with, each of them recorded in the csv
# header under its upper-case name, so that both the database and the units it is
# calculated in can be attributed
PACKAGES = ["posted", "team"]


def header(package):
    """The csv header line the version of one package is recorded under."""
    return f"{package.upper()} version"


def sources_md5():
    """md5 over both scripts, identical to a concatenation of tools::md5sum()."""
    digest = hashlib.md5()
    for source in SOURCE_FILES:
        digest.update(source.read_bytes())
    return digest.hexdigest()


def installed(package):
    """Installed package as version, url, commit and editable, from the PEP 610
    direct_url.json that pip and uv write; None if not installed."""
    try:
        dist = metadata.distribution(package)
    except metadata.PackageNotFoundError:
        return None
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    return {"version": dist.version, "url": direct.get("url"),
            "commit": (direct.get("vcs_info") or {}).get("commit_id"),
            "editable": bool((direct.get("dir_info") or {}).get("editable"))}


def identity(installation):
    """What the values of an installation are attributed to: its commit, its
    version, or the folder of an editable install that has no commit."""
    if installation is None:
        return None
    return (f"editable {installation['url']}" if installation["editable"]
            else installation["commit"] or installation["version"])


def expected_versions(installations):
    """The versions the values are attributed to: the commits pinned as git
    dependencies in pyproject.toml, or an installed package where nothing is."""
    with (REMIND_FOLDER / "pyproject.toml").open("rb") as pyproject:
        dependencies = tomllib.load(pyproject)["project"]["dependencies"]
    found = {}
    for package, here in installations.items():
        match = [dep for dep in dependencies
                 if dep.replace(" ", "").startswith(f"{package}@git+")]
        found[package] = match[0].rsplit("@", 1)[-1] if match else identity(here)
    return found


def csv_header(path):
    """The package versions and technoeconomic md5 recorded in a GAMS csv
    header, missing ones as "none"."""
    found = {**{name: "none" for name in PACKAGES}, "md5": "none"}
    if not path.is_file():
        return found
    keys = {**{header(package): package for package in PACKAGES},
            "technoeconomic md5": "md5"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("*"):
            break
        for key, name in keys.items():
            if line.startswith(f"* {key}:"):
                found[name] = line.split(":", 1)[1].strip()
    return found


def check(path):
    """Whether the csv at path is up to date with these scripts and the pinned
    versions of all PACKAGES. Returns an exit code and a message: 0 up to date,
    1 outdated or missing, 3 an editable install rebuilds it every run."""
    installations = {package: installed(package) for package in PACKAGES}
    editable = [package for package, here in installations.items()
                if here and here["editable"]]
    if editable:
        return 3, (f"{', '.join(editable)} installed in editable mode from "
                   f"{', '.join(installations[package]['url'] for package in editable)}, "
                   f"so {path} is rebuilt on every run and must not be committed.")
    expected = expected_versions(installations)
    found, md5 = csv_header(path), sources_md5()
    differences = [f"{package} {found[package]}, expected {expected[package] or 'none'}"
                   for package in PACKAGES if found[package] != expected[package]]
    if found["md5"] != md5:
        differences.append(f"technoeconomic md5 {found['md5']}, expected {md5}")
    if differences:
        return 1, (f"{path} is outdated ({'; '.join(differences)}). Regenerate it "
                   "with 'Rscript scripts/input/create_input_for_technoeconomic.R' "
                   "and commit it.")
    versions = "; ".join(f"{package} {expected[package]}" for package in PACKAGES)
    return 0, f"{path} is up to date with {versions}."


def format_value(value):
    """Format a value for GAMS. Exact zeros become EPS so that GAMS stores
    them and the overwrite in core/datainput.gms applies to them as well."""
    if not math.isfinite(value):
        raise ValueError(f"non-finite value {value}")
    return "EPS" if value == 0 else f"{value:.6g}"


def unit_lines(selected):
    """Comment and value lines, where one comment introduces all the rows that
    share its unit, until the next comment introduces the rows below it."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for (prop, tech), (_, value, unit) in sorted(selected.items()):
        grouped.setdefault((prop, unit), []).append(f"{prop},{tech},{format_value(value)}")
    for (prop, unit), values in grouped.items():
        yield f"* unit {prop} -> {unit}"
        yield from values


def write_gams(path, selected, versions, md5):
    lines = [
        "* description: techno-economic data from POSTED, averaged across "
        "sources; replaces fm_dataglob values from generisdata_tech.prn",
        "* origin: technoeconomic/create_input.py and content.py, regenerate "
        "with scripts/input/create_input_for_technoeconomic.R and commit",
        *(f"* {header(package)}: {version}" for package, version in versions.items()),
        f"* technoeconomic md5: {md5}",
        "* columns: char,te,value; a comment gives the unit of the rows below "
        "it, up to the next comment",
    ]
    # GAMS reads exactly one value per record here, and rejects even blank lines,
    # but it does ignore comment lines inside the data definition of
    # f_technoeconomic, which is where the units of the values can go
    lines.extend(unit_lines(selected))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="GAMS input file in fm_dataglob shape")
    parser.add_argument("--check", action="store_true",
                        help="report whether --out is up to date and exit")
    args = parser.parse_args(argv)

    if args.check:
        code, text = check(args.out)
        print(text)
        raise SystemExit(code)
    installations = {package: installed(package) for package in PACKAGES}
    expected = expected_versions(installations)
    wrong = []
    for package, here in installations.items():
        # an editable install is what a developer of POSTED or TEAM works with,
        # its values are attributed to its folder, not to a commit
        if here and here["editable"]:
            continue
        if identity(here) != expected[package]:
            wrong.append(f"{package} should be {expected[package]}, "
                         f"{sys.executable} has {identity(here) or 'nothing'}")
    if wrong:
        sys.exit(f"{' and '.join(wrong)}. Run 'uv sync' or update pyproject.toml.")
    # only the fetch needs POSTED, so that --check runs without it
    import content

    selected = content.fetch()
    versions = {package: identity(here) for package, here in installations.items()}
    md5 = sources_md5()
    write_gams(args.out, selected, versions, md5)
    listed = ", ".join(f"{package} {version}" for package, version in versions.items())
    print(f"Wrote {len(selected)} values to {args.out} "
          f"({listed}, technoeconomic md5 {md5})")


if __name__ == "__main__":
    main()
