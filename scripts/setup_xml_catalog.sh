#!/usr/bin/env bash
# Make `ament_xmllint` independent of DNS/network.
#
# Why: every package.xml carries
#   <?xml-model href="http://download.ros.org/schema/package_format3.xsd" ...?>
# so libxml2 resolves that schema over the network on every lint run. On a slow or
# flaky link it blows through ament_add_test's default `TIMEOUT 60` and ctest reports
# "did not generate a result file" - a false red that is hard to attribute.
#
# What: fetch the schema once, then map the URL to the local copy through an XML
# catalog that libxml2 reads by default (/etc/xml/catalog -> nextCatalog). After this,
# ament_xmllint runs in ~60 ms and no longer depends on the network.
#
# Usage: sudo bash scripts/setup_xml_catalog.sh
set -eu

XSD_URL="${XSD_URL:-http://download.ros.org/schema/package_format3.xsd}"
XSD_DIR="${XSD_DIR:-/usr/share/xml/ros}"
CATALOG="${CATALOG:-/etc/xml/ros-catalog.xml}"
SYSTEM_CATALOG="${SYSTEM_CATALOG:-/etc/xml/catalog}"

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo bash $0" >&2
  exit 1
fi

mkdir -p "$XSD_DIR"
if [ ! -s "$XSD_DIR/package_format3.xsd" ]; then
  echo "fetching $XSD_URL"
  curl -fsSL --max-time 60 "$XSD_URL" -o "$XSD_DIR/package_format3.xsd"
fi

xmlcatalog --noout --create "$CATALOG"
xmlcatalog --noout --add "uri" "$XSD_URL" "file://$XSD_DIR/package_format3.xsd" "$CATALOG"
xmlcatalog --noout --add "rewriteSystem" "http://download.ros.org/schema" "file://$XSD_DIR" "$CATALOG"
xmlcatalog --noout --add "rewriteURI" "http://download.ros.org/schema" "file://$XSD_DIR" "$CATALOG"

if [ -f "$SYSTEM_CATALOG" ]; then
  cp -n "$SYSTEM_CATALOG" "$SYSTEM_CATALOG.bak" 2>/dev/null || true
  if ! grep -q 'ros-catalog.xml' "$SYSTEM_CATALOG"; then
    xmlcatalog --noout --add nextCatalog "" "$(basename "$CATALOG")" "$SYSTEM_CATALOG"
  fi
else
  mkdir -p "$(dirname "$SYSTEM_CATALOG")"
  cat > "$SYSTEM_CATALOG" <<EOF
<?xml version="1.0"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <nextCatalog catalog="$(basename "$CATALOG")"/>
</catalog>
EOF
fi

echo "catalog written: $CATALOG"
echo "verify with: time xmllint --noout --schema $XSD_URL <some package.xml>"
