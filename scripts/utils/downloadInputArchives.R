library(glue)

source("scripts/start/defineInputData.R")

downloadInputData <- function(mapping, extramapping = "") {
  source("config/default.cfg")
  cfg$regionmapping <- mapping
  cfg$extramappings_historic <- extramapping
  data <- defineInputData(cfg)

  target <- Sys.getenv("REMIND_repos_dirs")[1]

  for (f in data$input) {
    if (startsWith(f, "rev")) {
      remote_path <- glue::glue("hpc.pik-potsdam.de:/p/projects/rd3mod/inputdata/output/{f}")
    } else if (startsWith(f, "CES")) {
      remote_path <- glue::glue("hpc.pik-potsdam.de:/p/projects/remind/inputdata/CESparametersAndGDX/{f}")
    } else {
      stop("No idea where to find: ", f)
    }

    status <- system2("rsync", args = c("-aP", remote_path, target))
    if (status != 0) {
      warning(glue::glue("Failed to sync {f} from {remote_path}"))
    }
  }
}

downloadInputData("config/regionmappingH12.csv")
downloadInputData("config/regionmapping_21_EU11.csv", "config/extramapping_EU27.csv")
