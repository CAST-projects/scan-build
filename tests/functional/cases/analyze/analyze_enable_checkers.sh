#!/usr/bin/env bash

# RUN: bash %s %T/enable_checkers
# RUN: cd %T/enable_checkers; %{analyze-build} -o . --enable-checker debug.ConfigDumper --cdb input.json | ./check.sh

set -o errexit
set -o nounset
set -o xtrace

# the test creates a subdirectory inside output dir.
#
# ${root_dir}
# ├── input.json
# ├── check.sh
# └── src
#    └── empty.c

root_dir=$1
mkdir -p "${root_dir}/src"

touch "${root_dir}/src/empty.c"

cat >> "${root_dir}/input.json" << EOF
[
    {
        "directory": "${root_dir}",
        "file": "${root_dir}/src/empty.c",
        "command": "cc -c ./src/empty.c -o ./src/empty.o"
    }
]
EOF

checker_file="${root_dir}/check.sh"
cat >> ${checker_file} << EOF
#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o xtrace

runs=\$(grep "exec command" | sort | uniq)

assert_present() {
    local pattern="\$1";
    local message="\$2";

    if [ \$(echo "\$runs" | grep -- "\$pattern" | wc -l) -eq 0 ]; then
        echo "\$message" && false;
    fi
}

assert_not_present() {
    local pattern="\$1";
    local message="\$2";

    if [ \$(echo "\$runs" | grep -- "\$pattern" | wc -l) -gt 0 ]; then
        echo "\$message" && false;
    fi
}


assert_present "debug.ConfigDumper" "checker name present"
assert_present "-analyzer-checker" "enable checker flag present"
assert_not_present "-analyzer-disable-checker" "disable checker flag missing"
EOF
chmod +x ${checker_file}
