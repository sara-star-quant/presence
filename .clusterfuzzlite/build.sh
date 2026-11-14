#!/bin/bash -eu
# presence is stdlib-only plus an optional cryptography dep, so there is
# nothing to install beyond the Dockerfile. The harnesses import from lib/.
for fuzzer in "$SRC"/presence/fuzz/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer" --paths "$SRC/presence/lib"
done
