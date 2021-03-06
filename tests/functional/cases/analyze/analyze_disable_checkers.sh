#!/usr/bin/env bash

# RUN: bash %s %T/disable_checkers
# RUN: cd %T/disable_checkers; %{analyze-build} -o . --status-bugs --disable-checker core.NullDereference --cdb input.json

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
