#!/usr/bin/env bash
# Rebuild app/static/vendor/tailwind.css from the classes used in the templates.
#
# The admin pages used to pull Tailwind from cdn.tailwindcss.com, which compiles
# classes in the browser on every page load. That is a development bundle —
# Tailwind's own docs say not to ship it — and when the CDN is unreachable, from
# a campus network that blocks it or on a bad connection, the admin page loses
# its entire layout and renders as an unusable column.
#
# So the CSS is built here and served from /static. Run this after adding
# Tailwind classes to a template, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="3.4.17"   # keep in step with what the templates were written against

npx --yes "tailwindcss@${VERSION}" \
  --input  <(printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n') \
  --output app/static/vendor/tailwind.css \
  --content "app/templates/**/*.html,app/static/js/**/*.js" \
  --minify

echo "Wrote app/static/vendor/tailwind.css — commit it."
