# DepthSensor

This repo is very much work in progress, and is open source primarily to be installable with SetupHelper

### Disclaimer
I'm not responsible for the usage of this script. Use on own risk! 

### Purpose
The script reads sensor data from a Gamicos GLT500 depth sensor (https://www.gamicos.com/Products/GLT500-Pressure-Level-Sensor) connected to a Cerbo over RS485, and publishes the information on the dbus as the service com.victronenergy.tank.dcp_tank_level

### Install

Install by adding to SetupHelper (need to be installed first)

### Debugging

The logs can be checked with ```tail -n 100 -F /data/DepthSensor/current | tai64nlocal```

The service status can be checked with svstat: ```svstat /service/DepthSensor```

This will output somethink like ```/service/DepthSensor: up (pid 5845) 185 seconds```


### Compatibility
Currently testing with Cerbo GX Mk2, Venus OS version v3.42
