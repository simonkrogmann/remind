# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de

create_input_for_technoeconomic <- function(cfg, remindPath = ".") {

  # ---- run the Python fetch. It writes global data only, no regional
  # ---- aggregation happens there, it is done below with madrat.

  pythonBin <- "python3"
  if (! is.null(cfg$pythonPath) && nzchar(cfg$pythonPath)) {
    pythonDir <- path.expand(sub("[/]$", "", cfg$pythonPath))
    pythonBin <- if (identical(.Platform$OS.type, "windows")) {
      file.path(pythonDir, "python.exe")
    } else {
      file.path(pythonDir, "bin", "python")
    }
    if (! file.exists(pythonBin)) {
      stop("No Python interpreter found in cfg$pythonPath ('", cfg$pythonPath,
           "') - correct cfg$pythonPath or set it to '' to use the system Python.")
    }
  }

  scriptfile <- file.path(remindPath, "technoeconomic", "posted.py")
  rawfile <- file.path(remindPath, "technoeconomic", "technoeconomic-raw.csv")
  cat("Running", pythonBin, scriptfile, "...\n")
  output <- system2(pythonBin, shQuote(scriptfile), stdout = TRUE, stderr = TRUE)
  cat(paste(output, collapse = "\n"), "\n")
  if (! is.null(attr(output, "status")) && attr(output, "status") != 0) {
    stop("Failed to run ", scriptfile, ". Is POSTED installed? See ",
         "config/py_requirements.txt and make create-conda.")
  }

  # ---- aggregate regions to the REMIND region resolution

  raw <- read.delim(rawfile, sep = ";")
  mappingfile <- file.path(remindPath, if (is.null(cfg$regionmapping)) "config/regionmappingH12.csv" else cfg$regionmapping)
  mapping <- madrat::toolGetMapping(mappingfile)
  if (all(raw$region == "global")) {
    # POSTED TEDFs without regional resolution: broadcast global values to
    # all REMIND regions.
    globalrows <- raw[raw$region == "global", , drop = FALSE]
    raw <- do.call(rbind, lapply(sort(unique(mapping$RegionCode)), function(regionsub) {
      newrows <- globalrows
      newrows$region <- regionsub
      newrows
    }))
  } else {
    mapped <- mapping$RegionCode[match(raw$region, mapping$CountryCode)]
    raw$region <- ifelse(is.na(mapped) & raw$region %in% mapping$RegionCode,
                         raw$region, mapped)
    if (anyNA(raw$region)) {
      stop("These POSTED regions are unknown in ", mappingfile, ": ",
           paste(sort(unique(raw$region[is.na(raw$region)])), collapse = ", "))
    }
  }
  agg <- aggregate(value ~ property + tech + year + region, data = raw, FUN = median)
  agg <- agg[order(agg$property, agg$tech, agg$year, agg$region), ]

  # ---- write technoeconomic.csv and copy it into core/input

  units <- sapply(sort(unique(raw$property)), function(prop) {
    paste0(prop, " (", raw$unit[raw$property == prop][1], ")")
  })
  header <- c(
    "* Techno-economic data fetched from POSTED (https://github.com/PhilippVerpoort/posted),",
    "* medians across all sources. Read by core/datainput.gms into p_technoeconomic.",
    paste0("* POSTED version: ", cfg$postedVersion),
    paste("* created:", format(Sys.time(), "%Y-%m-%d %H:%M:%S"),
          "by scripts/input/create_input_for_technoeconomic.R",
          "using technoeconomic/posted.py,",
          paste0("regionmapping ", basename(mappingfile), ".")),
    paste0("* units: ", paste(units, collapse = ", "), "."),
    "* data columns: property,tech,year,region,value"
  )
  records <- with(agg, paste(property, tech, year, region,
                             trimws(format(value, digits = 6)), sep = ","))
  outfile <- file.path(remindPath, "technoeconomic", "technoeconomic.csv")
  writeLines(c(header, records), outfile)
  copied <- file.copy(outfile, file.path(remindPath, "core", "input"), overwrite = TRUE)
  if (! copied) stop("Could not copy ", outfile, " to core/input/.")
  cat("Wrote", nrow(agg), "values to", outfile, "and core/input/", basename(outfile), "\n")
}

if (! interactive() && any(grepl("^--file=", commandArgs(trailingOnly = FALSE)))) {
  remindPath <- "."
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) > 0) remindPath <- args[1]
  cfg <- gms::readDefaultConfig(remindPath)
  create_input_for_technoeconomic(cfg, remindPath = remindPath)
}
