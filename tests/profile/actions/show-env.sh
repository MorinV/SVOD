#!/usr/bin/env bash
# Print the environment Svod gives an action, the arguments and the working directory.
env | grep '^SVOD_' | grep -v '^SVOD_LAUNCHED=' | sort
echo "ARGS=$*"
echo "PWD=$(pwd)"
exit "${SVOD_FM_EXIT:-0}"
