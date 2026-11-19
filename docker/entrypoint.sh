#!/bin/sh
set -eu

# With no explicit Cloud Run/Docker command, execute the small PIT correctness
# demo. Otherwise dispatch the requested installed project command unchanged.
if [ "$#" -eq 0 ]; then
    set -- demo-future-event-invariance
fi

exec "$@"
