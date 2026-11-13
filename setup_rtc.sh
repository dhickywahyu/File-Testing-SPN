#!/bin/bash

# Enable I2C to allow raspi read time from RTC
enable_i2c() {
    sudo raspi-config nonint do_i2c 0
}

# Add dtoverlay to define the type of RTC used
check_boot_config() {
    BOOT_FILE="/boot/config.txt"
    BOOT_LINE="dtoverlay=i2c-rtc,ds3231"

    # Check if the line exists
    if ! grep -Fxq "$BOOT_LINE" "$BOOT_FILE"; then
        echo "$BOOT_LINE" | sudo tee -a "$BOOT_FILE" > /dev/null
        echo "RTC overlay added to $BOOT_FILE."
    else
        echo "RTC overlay already exists in $BOOT_FILE."
    fi
}

# Replace HWClock content with this to disable fake-hwclock
replace_hwclock_content() {
    sudo cat > /lib/udev/hwclock-set << 'EOF'
#!/bin/sh
# Reset the System Clock to UTC if the hardware clock from which it
# was copied by the kernel was in localtime.

dev=$1

#if [ -e /run/systemd/system ] ; then
#    exit 0
#fi

/sbin/hwclock --rtc=$dev --systz
/sbin/hwclock --rtc=$dev --hctosys
EOF
}

# Create a script file for sync RTC time
add_update_rtc_time_script() {
    FILE_TIME_SCRIPT="/etc/systemd/system/update-rtc-time.sh"
    sudo rm -rf $FILE_TIME_SCRIPT
    sudo cat > $FILE_TIME_SCRIPT << 'EOF'
#!/bin/bash

# Function to check for internet connection
check_internet() {
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        return 0  # Internet available
    else
        return 1  # No internet
    fi
}

# Function to sync time if internet is available
sync_time() {
    # Check if RTC is detected or not
    TIME_RESPONSE="$(sudo timedatectl 2>&1)"
    ERROR_RTC="Remote I/O error"

    if echo "$TIME_RESPONSE" | grep -q "$ERROR_RTC"; then
        echo "RTC module not connected"
        sudo timedatectl set-ntp true
        sudo fake-hwclock load
        sudo fake-hwclock save
        exit 0
    else
        echo "RTC module detected"
        sudo hwclock -s
    fi

    I2C_BUS=1  # Change to 0 if using GPIO pins 0/1 for I2C
    ADDRESS="UU"  # Common I2C address for DS3231

    # Check if RTC is configured or not
    if i2cdetect -y $I2C_BUS | grep -q "$ADDRESS"; then
        echo "RTC module configured at address $ADDRESS."
    else
        echo "No RTC detected on I2C bus $I2C_BUS."
        sudo timedatectl set-ntp true
        sudo fake-hwclock load
        sudo fake-hwclock save
	    exit 0
    fi
	
    if check_internet; then
        echo "Internet detected. Syncing time with NTP..."
        sudo timedatectl set-ntp true
        sudo timedatectl set-ntp false
        sudo hwclock -w
        echo "Time successfully synced."
    else
        echo "No internet connection. Skipping time sync."
    fi
}

# Run the sync process
sync_time
EOF
    sudo chmod +x $FILE_TIME_SCRIPT
}

# Create a service file for sync RTC time
add_update_rtc_time_service() {
    sudo rm -rf /etc/systemd/system/update-rtc-time.service
    sudo cat > /etc/systemd/system/update-rtc-time.service << 'EOF'
[Unit]
Description=Run my Bash script periodically
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash /etc/systemd/system/update-rtc-time.sh
User=root
Group=root
Restart=always
RestartSec=300  # Runs every 5 minutes
ExecStartPre=/bin/sleep 23

[Install]
WantedBy=multi-user.target
EOF
}

add_systemctl_service() {
    sudo systemctl enable update-rtc-time.service
    sudo systemctl start update-rtc-time.service
}

reboot_system() {
    sudo reboot now
}

enable_i2c
check_boot_config
replace_hwclock_content
add_update_rtc_time_script
add_update_rtc_time_service
add_systemctl_service
# reboot_system
