#!/bin/sh
# Legt einen Starter (Programmmenü) an und heftet ERG-Training ins GNOME-Dock.
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/ergtraining.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=ERG-Training
Comment=Smart-Trainer-Steuerung (FTMS) mit FTP-Workouts
Exec=$DIR/start.sh
Icon=$DIR/icon.svg
Terminal=false
Categories=Sports;Utility;
StartupWMClass=Ergtraining
EOD
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
if command -v gsettings >/dev/null; then
    cur=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null)
    case "$cur" in
        *ergtraining.desktop*) ;;
        "@as []"|"") gsettings set org.gnome.shell favorite-apps "['ergtraining.desktop']" ;;
        *) gsettings set org.gnome.shell favorite-apps "$(echo "$cur" | sed "s/]\$/, 'ergtraining.desktop']/")" ;;
    esac
fi
echo "Fertig: ERG-Training ist im Programmmenü und im Dock."
