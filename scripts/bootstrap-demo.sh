#!/bin/sh
set -eu

origin=/tmp/seravops-demo-origin.git
working=/tmp/seravops-demo

if [ ! -d "$origin" ]; then
    git init --bare --initial-branch=main "$origin"
fi

if [ ! -d "$working/.git" ]; then
    git clone "$origin" "$working"
    git -C "$working" config user.name "Seravops Demo"
    git -C "$working" config user.email "demo@seravops.local"
    printf '%s\n' '# Seravops deployment demo' > "$working/README.md"
    git -C "$working" add README.md
    git -C "$working" commit -m "Initial demo revision"
    git -C "$working" push -u origin main
fi

exec "$@"

