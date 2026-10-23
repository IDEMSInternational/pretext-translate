#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e

# ==========================================
# CONFIGURATION
# ==========================================
# Update this version number based on the latest release at:
# https://okapiframework.org/binaries/main/
OKAPI_VERSION="1.48.0"
DOWNLOAD_URL="https://okapiframework.org/binaries/main/${OKAPI_VERSION}/okapi-apps_gtk2-linux-x86_64_${OKAPI_VERSION}.zip"
# DOWNLOAD_URL="https://okapiframework.org/binaries/main/1.48.0/okapi-apps_gtk2-linux-x86_64_1.48.0.zip"

INSTALL_DIR="/opt/okapi"
BIN_DIR="/usr/local/bin"

# ==========================================
# PRE-FLIGHT CHECKS
# ==========================================
echo "--- Okapi Framework System Installer ---"

# 1. Ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root. Try: sudo $0" 
   exit 1
fi

# 2. Check for required dependencies (wget, unzip, java)
for cmd in wget unzip java; do
    if ! command -v $cmd &> /dev/null; then
        echo "ERROR: '$cmd' is required but not installed."
        echo "Please install it (e.g., 'apt install default-jre wget unzip') and try again."
        exit 1
    fi
done

# ==========================================
# DOWNLOAD & EXTRACTION
# ==========================================
# Create a secure temporary directory
TMP_DIR=$(mktemp -d)
echo "=> Downloading Okapi Framework v${OKAPI_VERSION}..."
wget -q --show-progress -O "$TMP_DIR/okapi.zip" "$DOWNLOAD_URL"

echo "=> Extracting archive..."
unzip -q "$TMP_DIR/okapi.zip" -d "$TMP_DIR/okapi_extracted"

# Find the exact directory containing the Okapi executables
TIKAL_PATH=$(find "$TMP_DIR/okapi_extracted" -name "tikal.sh" | head -n 1)

if [ -z "$TIKAL_PATH" ]; then
    echo "ERROR: tikal.sh not found in the downloaded archive."
    exit 1
fi

# Get the parent folder of tikal.sh
ACTUAL_APP_DIR=$(dirname "$TIKAL_PATH")

# ==========================================
# INSTALLATION
# ==========================================
if [ -d "$INSTALL_DIR" ]; then
    echo "=> Removing previous installation at $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
fi

echo "=> Moving files to $INSTALL_DIR..."
mv "$ACTUAL_APP_DIR" "$INSTALL_DIR"

# Ensure all bundled shell scripts are executable
chmod +x "$INSTALL_DIR"/*.sh

# ==========================================
# SYSTEM PATH CONFIGURATION
# ==========================================
echo "=> Creating symlinks in $BIN_DIR..."

# Link Tikal (The Okapi CLI utility)
# We drop the .sh extension for the symlink for cleaner CLI usage
# ln -sf "$INSTALL_DIR/tikal.sh" "$BIN_DIR/tikal"
# Optional: If you use the desktop environment, you can also link the GUI tools
# ln -sf "$INSTALL_DIR/rainbow.sh" "$BIN_DIR/rainbow"
# ln -sf "$INSTALL_DIR/ratel.sh" "$BIN_DIR/ratel"

# 2. Create the wrapper script pointing to the absolute /opt/okapi/lib path
echo '#!/usr/bin/env bash' | sudo tee /usr/local/bin/tikal > /dev/null

# 3. Add the Java execution command
# INSTALL_DIR is interpolated here (double-quoted) rather than left as
# "${INSTALL_DIR}" for the wrapper to expand at run time: it's a variable of
# this install script, not of the shell that later runs /usr/local/bin/tikal,
# so it would be empty there and leave `-cp "/lib/*"` with no jars on it --
# this previously produced "ClassNotFoundException:
# net.sf.okapi.applications.tikal.Main" on every run.
echo "java -Dfile.encoding=UTF-8 -Xmx1024m -cp \"${INSTALL_DIR}/lib/*\" net.sf.okapi.applications.tikal.Main \"\$@\"" | sudo tee -a /usr/local/bin/tikal > /dev/null

# 4. Make the new wrapper executable
sudo chmod +x /usr/local/bin/tikal

# ==========================================
# CLEANUP
# ==========================================
rm -rf "$TMP_DIR"

echo "=========================================="
echo "Installation Complete!"
echo "Okapi Framework is installed at: $INSTALL_DIR"
echo "You can now run Tikal from any directory."
echo ""
echo "Test the installation by running: tikal -v"
echo "=========================================="


# 1. Remove the broken symlink
# sudo rm /usr/local/bin/tikal

# #!/bin/sh

# sudo apt update
# sudo apt install default-jre

# # Example for a recent stable version
# wget https://okapiframework.org
# unzip okapi-apps_all.zip -d ~/okapi

# cd ~/okapi
# chmod +x tikal.sh
# # ./tikal.sh -h

# sudo ln -s ~/okapi/tikal.sh /usr/local/bin/tikal
