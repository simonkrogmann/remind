# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de

# Techno-economic data from POSTED (https://github.com/PhilippVerpoort/posted)
#
# technoeconomic/content.py fetches the values configured in its QUERIES from
# POSTED and calculates the properties with TEAM
# (https://github.com/PhilippVerpoort/team), technoeconomic/create_input.py
# writes them into core/input/f_technoeconomic.csv, which core/datainput.gms
# reads to replace values from generisdata_tech.prn. The csv is committed and
# records in its header which POSTED and TEAM commits and which version of the
# scripts produced it.
#
# Checking is done by create_input.py --check run with 'uv run --no-sync',
# technoeconomicCheck returns its exit code and message: 0 up to date, 1
# outdated, 3 an editable install rebuilds the csv on every run, NA if uv or its
# .venv is missing.
# checkTechnoeconomicInput turns code 1 into the message that
# scripts/start/prepare.R and the tests stop on, reports 3 and NA and ignores
# them, and stops on any other exit code, which means the check did not run
# through. create_input_for_technoeconomic regenerates the csv with 'uv run',
# which syncs the .venv with the POSTED and TEAM commits pinned in
# pyproject.toml, the only place where REMIND touches the Python environment.
# It never does so without an environment to run in, and never skips it while an
# editable install rebuilds the csv on every run.
#
# Standalone: Rscript scripts/input/create_input_for_technoeconomic.R [remindPath] [--force]

# run create_input.py --check without touching the environment, returns its
# exit code and message, code NA without uv or its .venv
technoeconomicCheck <- function(remindPath = ".") {
  remindPath <- normalizePath(remindPath, mustWork = FALSE)
  uv <- Sys.which("uv")
  if (! nzchar(uv) || ! dir.exists(file.path(remindPath, ".venv"))) {
    return(list(status = NA_integer_,
                message = paste("Neither uv nor its .venv were found, core/input/f_technoeconomic.csv",
                                "is used as committed and unchecked. Run 'uv sync' to check it.")))
  }
  scriptfile <- file.path(remindPath, "technoeconomic", "create_input.py")
  # 127 for a uv that vanished after Sys.which, or a wd which does not exist,
  # so that checkTechnoeconomicInput stops on it in a controlled way
  result <- tryCatch(
    processx::run(uv, c("run", "--no-sync", "python", scriptfile, "--check"),
                  wd = remindPath, error_on_status = FALSE),
    error = function(e) list(status = 127L, stdout = e$message, stderr = ""))
  list(status = result$status, message = sub("\n+$", "", paste0(result$stdout, result$stderr)))
}

checkTechnoeconomicInput <- function(remindPath = ".") {
  check <- technoeconomicCheck(remindPath)
  if (identical(check$status, 1L)) return(check$message)
  # stay silent while everything is fine, report the codes that mean the csv
  # was not checked: 3 editable install, NA no uv or .venv
  if (is.na(check$status) || check$status %in% c(0L, 3L)) {
    if (! identical(check$status, 0L) && nzchar(check$message)) message(check$message)
    return(NULL)
  }
  # any other code means the check itself did not run through
  stop("technoeconomic/create_input.py --check exited with code ", check$status,
       ":\n", check$message)
}

# create the csv from POSTED, 'uv run' syncs the .venv with pyproject.toml
create_input_for_technoeconomic <- function(remindPath = ".", force = FALSE) {
  remindPath <- normalizePath(remindPath, mustWork = FALSE)
  scriptfile <- file.path(remindPath, "technoeconomic", "create_input.py")
  datafile <- file.path(remindPath, "core", "input", "f_technoeconomic.csv")

  check <- technoeconomicCheck(remindPath)
  if (identical(check$status, 0L) && ! force) {
    message(check$message, " Use force = TRUE to refetch.")
    return(invisible(datafile))
  }
  # without uv or its .venv nothing can be fetched, the committed csv stays as it
  # is. Every other code regenerates, 1 outdated and 3 editable install both do.
  if (is.na(check$status)) {
    message(check$message, " ", datafile, " is not regenerated.")
    return(invisible(NULL))
  }
  if (! identical(check$status, 1L) && nzchar(check$message)) message(check$message)
  uv <- Sys.which("uv")
  message("Fetching techno-economic data from POSTED with ", uv, " run.")
  result <- tryCatch(
    # uv run syncs the .venv with pyproject.toml before running the script
    processx::run(uv, c("run", "python", scriptfile, "--out", datafile),
                  wd = remindPath, error_on_status = FALSE),
    error = function(e) list(status = 127L, stdout = e$message, stderr = ""))
  cat(paste0(result$stdout, result$stderr))
  if (! identical(result$status, 0L)) {
    stop(scriptfile, " failed, see its output above.")
  }
  # code 1 means the fetch did not produce what was expected, code 3 reports
  # that an editable install wrote the file, so it must not be committed
  after <- technoeconomicCheck(remindPath)
  if (identical(after$status, 1L)) stop("After fetching: ", after$message)
  if (identical(after$status, 0L)) {
    message("Wrote ", datafile, ". Commit it together with technoeconomic/create_input.py ",
            "and content.py (git add -f core/input/f_technoeconomic.csv, the folder is git-ignored).")
  } else if (nzchar(after$message)) {
    message(after$message)
  }
  invisible(datafile)
}

# run standalone, not when this file is only sourced by prepare.R or a test
if (! interactive() && any(grepl("^--file=.*create_input_for_technoeconomic\\.R$", commandArgs(trailingOnly = FALSE)))) {
  args <- commandArgs(trailingOnly = TRUE)
  force <- "--force" %in% args
  args <- grep("^--", args, value = TRUE, invert = TRUE)
  remindPath <- if (length(args) > 0) args[1] else "."
  create_input_for_technoeconomic(remindPath = remindPath, force = force)
}
