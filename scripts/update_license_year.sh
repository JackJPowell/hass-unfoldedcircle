#!/bin/bash

YEAR=$(date +"%Y")

# GNU sed — no need for '' after -i
sed -E -i "s/(Copyright( \(c\)| ©)? [0-9]{4})(–[0-9]{4})?/\1–$YEAR/" LICENSE