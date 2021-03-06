#!/usr/bin/env bash

# RUN: bash %s %T/multiple_source_build
# RUN: cd %T/multiple_source_build; %{intercept-build} --cdb result.json ./run.sh
# RUN: cd %T/multiple_source_build; cdb_diff result.json expected.json

set -o errexit
set -o nounset
set -o xtrace

# the test creates a subdirectory inside output dir.
#
# ${root_dir}
# ├── run.sh
# ├── expected.json
# └── src
#    ├── main.c
#    ├── one.c
#    └── two.c

root_dir=$1
mkdir -p "${root_dir}/src"

touch "${root_dir}/src/one.c"
touch "${root_dir}/src/two.c"
cp "${test_input_dir}/main.c" "${root_dir}/src/main.c"

build_file="${root_dir}/run.sh"
cat >> ${build_file} << EOF
#!/usr/bin/env bash

set -o nounset
set -o xtrace

"\$CC" -Dver=1 src/one.c src/two.c src/main.c;

true;
EOF
chmod +x ${build_file}

cat >> "${root_dir}/expected.json" << EOF
[
{
  "command": "cc -c -Dver=1 src/one.c",
  "directory": "${root_dir}",
  "file": "src/one.c"
}
,
{
  "command": "cc -c -Dver=1 src/two.c",
  "directory": "${root_dir}",
  "file": "src/two.c"
}
,
{
  "command": "cc -c -Dver=1 src/main.c",
  "directory": "${root_dir}",
  "file": "src/main.c"
}
]
EOF
