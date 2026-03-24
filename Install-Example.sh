#!/bin/bash

# Exit on error
set -e

# Get the current username
USERNAME=$(whoami)
USER_HOME="/home/$USERNAME"
DESKTOP="$USER_HOME/Desktop"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo "=== Starting installation script ==="

# Update package list
echo "Updating package list..."
sudo apt update

# Install required packages from Ubuntu repositories
echo "Installing packages from Ubuntu repositories..."
sudo apt install -y python3 python3-tk python3-psutil brightnessctl xdotool x11-utils playerctl wmctrl xbindkeys udev curl git fonts-montserrat

# Install Openbox with removal if already installed
echo "Checking Openbox installation..."
if command_exists openbox; then
    echo "Openbox is already installed. Removing it first..."
    sudo apt remove -y openbox
    sudo apt install -y openbox
else
    echo "Installing Openbox..."
    sudo apt install -y openbox
fi

# Install Lutris from GitHub (latest release)
echo "Installing Lutris from GitHub..."
echo "Fetching latest Lutris release information..."

# Get the download URL for the .deb file from the latest release
LUTRIS_DEB_URL=$(curl -s https://api.github.com/repos/lutris/lutris/releases/latest | grep -o "https://.*_all\.deb" | head -1)

if [ -z "$LUTRIS_DEB_URL" ]; then
    echo "Error: Could not find Lutris .deb download URL"
    exit 1
fi

echo "Downloading from: $LUTRIS_DEB_URL"
wget -O lutris_latest.deb "$LUTRIS_DEB_URL"
sudo dpkg -i lutris_latest.deb || sudo apt-get install -f -y
rm lutris_latest.deb

# Install Pegasus frontend via flatpak
echo "Installing Pegasus frontend via flatpak..."
if ! command_exists flatpak; then
    sudo apt install -y flatpak
fi
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub org.pegasus_frontend.Pegasus

# Download a.py to home directory
echo "Downloading a.py..."
wget -O "$USER_HOME/a.py" "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/a.py"

# Make a.py executable
chmod +x "$USER_HOME/a.py"

# Create Launch.sh on desktop
echo "Creating Launch.sh on desktop..."
mkdir -p "$DESKTOP"
cat > "$DESKTOP/Launch.sh" << EOF
#!/bin/bash
/usr/bin/python3 $USER_HOME/a.py
EOF

# Make Launch.sh executable
chmod +x "$DESKTOP/Launch.sh"

# Download .xbindkeysrc
echo "Downloading .xbindkeysrc..."
wget -O "$USER_HOME/.xbindkeysrc" "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/.xbindkeysrc"

# Replace jarvis with current username in .xbindkeysrc
echo "Updating .xbindkeysrc with correct username..."
sed -i "s/jarvis/$USERNAME/g" "$USER_HOME/.xbindkeysrc"

# Install joystick configuration files
echo "Installing joystick configuration files..."
sudo mkdir -p /usr/share/X11/xorg.conf.d

# Download and install 50-joystick.conf
echo "Downloading 50-joystick.conf..."
wget -O /tmp/50-joystick.conf "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/50-joystick.conf"
sudo cp /tmp/50-joystick.conf /usr/share/X11/xorg.conf.d/50-joystick.conf

# Download and install 51-joystick-others.conf
echo "Downloading 51-joystick-others.conf..."
wget -O /tmp/51-joystick-others.conf "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/51-joystick-others.conf"
sudo cp /tmp/51-joystick-others.conf /usr/share/X11/xorg.conf.d/51-joystick-others.conf

# Clean up temporary files
rm -f /tmp/50-joystick.conf /tmp/51-joystick-others.conf

# Setup Pegasus theme
echo "Setting up Pegasus theme..."
THEMES_DIR="$USER_HOME/.var/app/org.pegasus_frontend.Pegasus/config/pegasus-frontend/themes"
mkdir -p "$THEMES_DIR"

echo "Cloning library theme repository..."
git clone https://github.com/Fr75s/library "$THEMES_DIR/library"

# Install Openbox autostart
echo "Installing Openbox autostart configuration..."
OPENBOX_CONFIG_DIR="$USER_HOME/.config/openbox"
mkdir -p "$OPENBOX_CONFIG_DIR"

echo "Downloading autostart file..."
wget -O "$OPENBOX_CONFIG_DIR/autostart" "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/autostart"

# Make autostart executable
chmod +x "$OPENBOX_CONFIG_DIR/autostart"

# Replace Xsession files (openbox.desktop and plasma.desktop)
echo "Replacing Xsession files..."
sudo mkdir -p /usr/share/xsessions

# Backup existing files if they exist
if [ -f /usr/share/xsessions/openbox.desktop ]; then
    echo "Backing up existing openbox.desktop..."
    sudo cp /usr/share/xsessions/openbox.desktop /usr/share/xsessions/openbox.desktop.bak
fi

if [ -f /usr/share/xsessions/plasma.desktop ]; then
    echo "Backing up existing plasma.desktop..."
    sudo cp /usr/share/xsessions/plasma.desktop /usr/share/xsessions/plasma.desktop.bak
fi

# Download and install new files
echo "Downloading openbox.desktop..."
sudo wget -O /usr/share/xsessions/openbox.desktop "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/openbox.desktop"

echo "Downloading plasma.desktop..."
sudo wget -O /usr/share/xsessions/plasma.desktop "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/plasma.desktop"

# Download and set wallpaper for KDE Plasma
echo "Downloading wallpaper..."
wget -O "$USER_HOME/Wallpaper.png" "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/Wallpaper.png"

# Apply wallpaper for KDE Plasma (for the current user)
echo "Setting wallpaper for KDE Plasma..."

# Create directory for plasma wallpaper configuration if it doesn't exist
mkdir -p "$USER_HOME/.config"

# Use kwriteconfig5 to set the wallpaper (works if run from within Plasma session)
if command_exists kwriteconfig5; then
    # Set the wallpaper for all activities
    kwriteconfig5 --file "$USER_HOME/.config/plasmarc" --group "Wallpapers" --key "Image" "file://$USER_HOME/Wallpaper.png"
    kwriteconfig5 --file "$USER_HOME/.config/plasmarc" --group "Wallpapers" --key "WallpaperPlugin" "org.kde.image"
    
    # Set the wallpaper for the current desktop
    kwriteconfig5 --file "$USER_HOME/.config/plasma-org.kde.plasma.desktop-appletsrc" --group "Containments" --group "1" --group "Wallpaper" --group "org.kde.image" --group "General" --key "Image" "file://$USER_HOME/Wallpaper.png"
    
    echo "Wallpaper configured for KDE. Changes will take effect after login."
else
    echo "kwriteconfig5 not found. KDE wallpaper will need to be set manually after installation."
    echo "The wallpaper file is located at: $USER_HOME/Wallpaper.png"
fi

# Replace SDDM configuration file
echo "Replacing SDDM configuration file..."

# Check if SDDM is installed
if command_exists sddm; then
    # Backup existing sddm.conf if it exists
    if [ -f /etc/sddm.conf ]; then
        echo "Backing up existing sddm.conf..."
        sudo cp /etc/sddm.conf /etc/sddm.conf.bak
    fi
    
    # Download and install the new sddm.conf
    echo "Downloading sddm.conf..."
    sudo wget -O /etc/sddm.conf "https://raw.githubusercontent.com/ownessowen-stack/ReleaseTheDeckFiles/main/sddm.conf"
    
    # Replace jarvis with current username in sddm.conf
    echo "Updating sddm.conf with correct username..."
    sudo sed -i "s/jarvis/$USERNAME/g" /etc/sddm.conf
    
    echo "SDDM configuration updated successfully."
else
    echo "SDDM is not installed. Skipping SDDM configuration..."
    echo "Note: SDDM will be configured if installed later."
fi

# Add sudoers entry for nvpmodel
echo "Adding sudoers entry for nvpmodel..."

# Create a temporary file for the new sudoers configuration
TMP_SUDOERS=$(mktemp)

# Backup current sudoers
sudo cp /etc/sudoers /etc/sudoers.bak

# Check if the entry already exists to avoid duplicates
if sudo grep -q "^$USERNAME ALL=(ALL) NOPASSWD: /usr/sbin/nvpmodel$" /etc/sudoers; then
    echo "sudoers entry already exists. Skipping..."
else
    # Create a new sudoers file with the entry placed after the %sudo line
    sudo awk -v user="$USERNAME" '
        /^%sudo[[:space:]]+ALL=\(ALL:ALL\) ALL$/ {
            print
            print user " ALL=(ALL) NOPASSWD: /usr/sbin/nvpmodel"
            next
        }
        { print }
    ' /etc/sudoers > "$TMP_SUDOERS"
    
    # Validate the new sudoers file
    if sudo visudo -c -f "$TMP_SUDOERS" 2>/dev/null; then
        # Install the new sudoers file
        sudo cp "$TMP_SUDOERS" /etc/sudoers
        echo "sudoers entry added successfully."
    else
        echo "ERROR: Invalid sudoers file. Changes not applied."
        echo "Please check the sudoers file manually."
        exit 1
    fi
fi

# Clean up
rm -f "$TMP_SUDOERS"

echo "=== Installation complete! ==="
echo "Files installed:"
echo "Notes:"
echo "  - Restart your system to fully apply changes"
echo "  - Options 'Gaming Mode' (Openbox) and 'Desktop Mode' (Plasma) are available at login"
echo "  - KDE wallpaper has been configured and will appear on reboot"
echo "  - SDDM is configured to auto-login into Openbox (Gaming Mode)"
