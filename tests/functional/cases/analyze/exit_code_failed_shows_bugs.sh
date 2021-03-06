#!/usr/bin/env bash

# XFAIL: *
# RUN: bash %s %T/exit_code_failed_shows_bugs
# RUN: cd %T/exit_code_failed_shows_bugs; %{analyze-build} -o . --status-bugs --cdb input.json

set -o errexit
set -o nounset
set -o xtrace

# the test creates a subdirectory inside output dir.
#
# ${root_dir}
# ├── input.json
# └── src
#    └── broken.c

root_dir=$1
mkdir -p "${root_dir}/src"

cp "${test_input_dir}/div_zero.c" "${root_dir}/src/broken.c"

cat >> "${root_dir}/input.json" << EOF
[
    {
        "directory": "${root_dir}",
        "file": "${root_dir}/src/broken.c",
        "command": "cc -c ./src/broken.c -o ./src/broken.o"
    }
]
EOF
