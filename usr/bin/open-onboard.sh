#!/bin/bash
# try to toggle keyboard if nnboard is already running
dbus-send --type=method_call --dest=org.onboard.Onboard /org/onboard/Onboard/Keyboard org.onboard.Onboard.Keyboard.ToggleVisible
# if nnboard not running open it
if [ $? -ne 0 ]; then
onboard
fi
