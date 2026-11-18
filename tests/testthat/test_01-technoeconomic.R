# |  (C) 2006-2026 Potsdam Institute for Climate Impact Research (PIK)
# |  authors, and contributors see CITATION.cff file. This file is part
# |  of REMIND and licensed under AGPL-3.0-or-later. Under Section 7 of
# |  AGPL-3.0, you are granted additional permissions described in the
# |  REMIND License Exception, version 1.0 (see LICENSE file).
# |  Contact: remind@pik-potsdam.de
test_that("core/input/f_technoeconomic.csv matches technoeconomic/create_input.py and the POSTED pin", {
  source("../../scripts/input/create_input_for_technoeconomic.R", local = TRUE)
  check <- technoeconomicCheck("../..")
  # without Python nothing was verified, and an editable POSTED install rebuilds
  # the csv on every run, so it is never committed
  skip_if(is.na(check$status), check$message)
  skip_if(identical(check$status, 3L), check$message)
  # NULL means up to date, otherwise a message telling how to regenerate the file
  expect_null(checkTechnoeconomicInput("../.."))
})
