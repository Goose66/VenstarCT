#!/usr/bin/python3
"""
Polglot v2 NodeServer for Venstar ColorTouch Thermostats
by Goose66 (W. Randy King) kingwrandy@gmail.com
"""
import sys
import re
import time
import venstarapi as api
import socket
from ipaddress import IPv4Address
import polyinterface

LOGGER = polyinterface.LOGGER

# contstants for ISY Nodeserver interface
ISY_BOOL_UOM =2 # Used for reporting status value for Controller node
ISY_INDEX_UOM = 25 # Custom index UOM for translating direction values
ISY_INDEX_PERCENT = 51 # UOM for percentages
ISY_TEMP_F_UOM = 17 # UOM for temperatures (farenheit)
ISY_TEMP_C_UOM = 4 # UOM for temperatures (celcius)
ISY_REL_HUMIDITY = 22 # UOM for relative humidity (percent)
ISY_TSTAT_MODE_UOM = 67 # UOM for thermostat mode
ISY_TSTAT_HCS_UOM = 66 # UOM for thermostat heat/cool state
ISY_TSTAT_FS_UOM = 68 # UOM for fan mode
ISY_TSTAT_FRS_UOM = 80 # UOM for fan runstate

# values for thermostat mode
IX_TSTAT_MODE_OFF = 0
IX_TSTAT_MODE_HEAT = 1
IX_TSTAT_MODE_COOL = 2
IX_TSTAT_MODE_AUTO = 3
IX_TSTAT_MODE_AWAY = 13

# values for schedule mode
IX_TSTAT_SCHED_MODE_ACTIVE = 0
IX_TSTAT_SCHED_MODE_INACTIVE = 255

# custom parameter values for this nodeserver
PARAM_HOSTNAMES = "hostname"
PARAM_PIN = "pin"

# Node class for temperature sensor
class Sensor(polyinterface.Node):

    id = "SENSOR"
    hint = [0x01, 0x03, 0x03, 0x00] # Residential/Sensor/Climate Sensor
    
    # Override init to handle temp units
    def __init__(self, controller, primary, addr, name, tempUnit):
        super(Sensor, self).__init__(controller, primary, addr, name)
    
        # override the parent node with the thermostat node (defaults to controller)
        self.parent = self.controller.nodes[self.primary]

        # set the temp unit before calling the parent class init()
        self.setTempUnit(tempUnit)

    # Setup the termostat node for the correct temperature unit (0-F or 1-C)
    def setTempUnit(self, tempUnit):
        
        # update the drivers in the node to the correct UOM
        # this is so the numbers show up in the Admin Console with the right unit
        for driver in self.drivers:
            if driver["driver"] in ("ST"):
                driver["uom"] = ISY_TEMP_C_UOM if tempUnit == 1 else ISY_TEMP_F_UOM
        
    drivers = [
        {"driver": "ST", "value": 0.0, "uom": ISY_TEMP_F_UOM},
        {"driver": "BATLVL", "value": 0, "uom": ISY_INDEX_PERCENT},
    ]

# Node class for thermostat
class Thermostat(polyinterface.Node):

    id = "THERMOSTAT"
    hint = [0x01, 0x0C, 0x01, 0x00] # Residential/HVAC/Thermostat
    tempUnit = 0
    _hostName = ""
    _type = ""
    _conn = None
    
    # Override init to handle temp units
    def __init__(self, controller, primary, addr, name, hostName=None, type=None, tempUnit=None):

        if hostName is None:
        
            # retrieve the thermostat properties from polyglot custom data
            # Note: use controller and addr parameters instead of self.controller and self.address
            # because parent class init() has not been called yet
            cData = controller.getCustomData(addr).split(";")
            self._hostName = cData[0]
            self._type = cData[1]
            self.tempUnit = int(cData[2])

        else:
            self._hostName = hostName
            self._type = type
            self.tempUnit = tempUnit

        # setup the temp unit before calling the parent class init()
        self.setTempUnit(self.tempUnit)

        # call the parent class init
        super(Thermostat, self).__init__(controller, addr, addr, name) # send own address as primary

        # make the thermostat a primary node
        # Note: this is to support grouping of child nodes, e.g., sensors
        self.isPrimary = True

        # create a connection object in the API for the the thermostat 
        self._conn = api.thermostatConnection(self._hostName, logger=LOGGER)

        # store instance variables in polyglot custom data
        self.saveProperties()

    # save object properties to custom data
    def saveProperties(self):

            # store instance variables in polyglot custom data
            cData = ";".join([
                self._hostName,
                self._type,
                str(self.tempUnit),
            ])
            self.controller.addCustomData(self.address, cData)

    # Setup the termostat node for the correct temperature unit (0-F or 1-C)
    def setTempUnit(self, tempUnit):
        
        # set the id of the node for the ISY to use from the nodedef
        # this is so the editor (range) for the setpoint is correct
        if tempUnit == 1:
            self.id = "THERMOSTAT_C"
        else:
            self.id = "THERMOSTAT"
            
        # update the drivers in the node to the correct UOM
        # this is so the numbers show up in the Admin Console with the right unit
        for driver in self.drivers:
            if driver["driver"] in ("ST", "CLISPH", "CLISPC"):
                driver["uom"] = ISY_TEMP_C_UOM if tempUnit == 1 else ISY_TEMP_F_UOM

    # Change the temperature unit for the thermostat node and update the ISY
    def changeTempUnits(self, tempUnit):
        
        # setup the UOMs and ID for the temperature unit
        self.setTempUnit(tempUnit)
        
        # update the node to Polyglot and the  ISY
        self.controller.updateNode(self)

        # spin through the child nodes of this thermostat and update the tempunit
        for addr in self.controller.nodes:

            # ignore the controller and this thermostat node
            if addr != self.address and addr != self.controller.address:

                # if the device is a Sensor node with this thermostat as the primary, change its temp unit
                node = self.controller.nodes[addr]
                if node.id == "SENSOR" and node.primary == self.address:
                    node.setTempUnit(tempUnit)

        # save the changed temp unit back to custom data
        self.tempUnit = tempUnit
        self.saveProperties()

    # Increase/decrease the active setpoint by one degree
    def cmd_inc_dec(self, command):

        LOGGER.info("Increase or decrease temperature of %s in command handler: %s.", self.name, str(command))

        # Get the state values for the thermostat since we are incrementing setpoints
        thermostatState = self._conn.getThermostatState()

        # if the thermostat is online
        if thermostatState:
    
            # get the current thermostat settings
            sph = thermostatState["heattemp"]
            spc = thermostatState["cooltemp"]
            mode = thermostatState["mode"]
            away = (thermostatState["away"] == 1)
            cmd = command["cmd"]

            # determine the setpoint to increase based on the mode
            if away:
                LOGGER.warning("Setpoint(s) not adjusted for thermostat in Away mode.")
            elif mode == api.THERMO_MODE_OFF:
                LOGGER.warning("Setpoint(s) not adjusted for thermostat in Off mode.")
            else:
                if mode in (api.THERMO_MODE_HEAT, api.THERMO_MODE_AUTO):
                    if cmd == "BRT":
                        sph += 1.0
                    else:
                        sph -= 1.0
                if mode in (api.THERMO_MODE_COOL, api.THERMO_MODE_AUTO):
                    if cmd == "BRT":
                        spc += 1.0
                    else:
                        spc -= 1.0

                # call the controls API to set the new setpoints
                if self._conn.setThermostatControls(heattemp=sph, cooltemp=spc):
                    self.setDriver("CLISPH", sph)
                    self.setDriver("CLISPC", spc)

                else:
                    LOGGER.error("Call to API setThermostatControls() failed in %s command handler.", cmd)

    # Set the thermostat heat setpoint to the specified value
    def cmd_set_sp(self, command):

        LOGGER.info("Set the setpoints for %s in command handler: %s", self.name, str(command))

        # Get the state values for the thermostat since we have to specify both setpoint values
        thermostatState = self._conn.getThermostatState()

        # if the thermostat is online
        if thermostatState:
    
            # get the current thermostat settings
            sph = thermostatState["heattemp"]
            spc = thermostatState["cooltemp"]
            mode = thermostatState["mode"]
            setpointDelta = thermostatState["setpointdelta"]
            away = (thermostatState["away"] == 1)
            cmd = command["cmd"]

            # can't change settings while in away mode
            if away:
                LOGGER.warning("Setpoint(s) not adjusted for thermostat in Away mode.")
            else:

                # replace setpoint with the specified value based on the command 
                if cmd == "SET_CLISPH":
                    sph = float(command["value"])
                else:
                    spc = float(command["value"])

                # make sure spc > sph by setpoint delta degrees if in auto mode
                if mode == api.THERMO_MODE_AUTO and (spc - sph) < setpointDelta:
                    LOGGER.warning("Difference between heat and cool setpoint(s) must be greater than or equal to %d degrees for thermostat in Auto mode.", setpointDelta)
                else:
                    
                    # call the controls API to set the new setpoints
                    if self._conn.setThermostatControls(heattemp=sph, cooltemp=spc):
                        self.setDriver("CLISPH", sph)
                        self.setDriver("CLISPC", spc)

                    else:
                        LOGGER.error("Call to API setThermostatControls() failed in %s command handler.", cmd)

    # Set the thermostat mode to the specified value
    def cmd_set_mode(self, command):

        LOGGER.info("Set the thermostat mode for %s in command handler: %s", self.name, str(command))

        # Get the state values for the thermostat since we have to specify both setpoint values
        thermostatState = self._conn.getThermostatState()

        # if the thermostat is online
        if thermostatState:
    
            # get the current thermostat settings
            sph = thermostatState["heattemp"]
            spc = thermostatState["cooltemp"]
            away = (thermostatState["away"] == 1)
            newMode = int(command.get("value"))

            # if new mode is Away mode, then call the API to set the away mode
            if newMode == IX_TSTAT_MODE_AWAY:
    
                # call the settings API to turn on away mode
                if not self._conn.setThermostatSettings(api.THERMO_SETTING_AWAY_STATE, 1):
                    LOGGER.error("Call to API setThermostatSettings() failed in SET_CLIMD command handler.")
                    return

            else:
                
                # if the thermostat is currently in away mode then take the thermostat out of away mode before setting new mode
                if away:

                    # call the settings API to turn off away mode
                    if not self._conn.setThermostatSettings(api.THERMO_SETTING_AWAY_STATE, 0):
                        LOGGER.error("Call to API setThermostatSettings() failed in SET_CLIMD command handler.")
                        return
            
                # call the controls API to set the thermostat mode
                if not self._conn.setThermostatControls(mode=newMode, heattemp=sph, cooltemp=spc):
                    LOGGER.error("Call to API setThermostatControls() failed in SET_CLIMD command handler.")
                    return
            
            self.setDriver("CLIMD", newMode)

    # Set the thermostat mode to the specified value
    def cmd_set_fan(self, command):

        LOGGER.info("Set the fan mode for %s in command handler: %s", self.name, str(command))

        # Get the state values for the thermostat since we can't modify the fan when in away mode
        thermostatState = self._conn.getThermostatState()

        # if the thermostat is online
        if thermostatState:
    
            # get the current thermostat settings
            away = (thermostatState["away"] == 1)
            fan = int(command.get("value"))    

            # can't change settings while in away mode
            if away:
                LOGGER.warning("Fan mode not adjusted for thermostat in Away mode.")
            else:
        
                # call the controls API to set fan mode
                if self._conn.setThermostatControls(fan=fan):
                    self.setDriver("CLIFS", fan)

                else:
                    LOGGER.error("Call to API setThermostatControls() failed in SET_CLIFS command handler.")

    # Set the schedule mode on
    def cmd_set_sched(self, command):
    
        LOGGER.info("Set schedule mode on for %s in command handler: %s", self.name, str(command))

        # Get the state values for the thermostat since we can't modify the fan when in away mode
        thermostatState = self._conn.getThermostatState()

        # if the thermostat is online
        if thermostatState:
    
            # get the current thermostat settings
            away = (thermostatState["away"] == 1)
            cmd = command["cmd"]

            # can't change settings while in away mode
            if away:
                LOGGER.warning("Schedule mode not adjusted for thermostat in Away mode.")
            else:
        
                schedMode = 1 if cmd == "SCHED_ON" else 0

                # call the settings API to set the schedule mode
                if self._conn.setThermostatSettings(api.THERMO_SETTING_SCHEDULE_STATE, schedMode):
                    
                    # update the schedule mode driver
                    self.setDriver("CLISMD", IX_TSTAT_SCHED_MODE_ACTIVE if schedMode == 1 else IX_TSTAT_SCHED_MODE_INACTIVE)

                else:
                    LOGGER.error("Call to API setThermostatSettings() failed in %s command handler.", cmd)

    # update the states for this thermostat
    def updateNodeStates(self, forceReport=False):
        
        # get the thermostat state from the API
        thermoState = self._conn.getThermostatState() 

        if thermoState:

            # set thermostat state to offline:
            self.setDriver("GV0", 1, True, forceReport) # Thermostat online

            # if the tempunits has changed, fix the node
            if thermoState["tempunits"] != self.tempUnit:
                self.changeTempUnits(thermoState["tempunits"])

            # udpate the remaining driver values
            self.setDriver("ST", float(thermoState["spacetemp"]), True, forceReport)
            self.setDriver("CLISPH", float(thermoState["heattemp"]), True, forceReport)
            self.setDriver("CLISPC", float(thermoState["cooltemp"]), True, forceReport)
            self.setDriver("CLIHUM", float(thermoState["hum"]), True, forceReport)
            # API thermostat mode utilizes values 0-3 (off, heat, cool, auto) and 13 (away) of ISY Thermostat mode UOM
            if thermoState["away"] == 1:
                self.setDriver("CLIMD", IX_TSTAT_MODE_AWAY, True, forceReport)
            else:
                self.setDriver("CLIMD", int(thermoState["mode"]), True, forceReport)
            # API thermostat fan mode translates directly to first two values (0-1) of ISY Fan mode UOM
            self.setDriver("CLIFS", int(thermoState["fan"]), True, forceReport)
            # API thermostat state translates directly to first three values (0-2) of ISY Thermostat heat/cool state UOM but has additional two values
            if thermoState["state"] in (0, 1, 2): 
                state = int(thermoState["state"])
            else:
                state = int(thermoState["state"]) + 10
            self.setDriver("CLIHCS", state, True, forceReport) 
            # API thermostat fan state mode translates directly to first two values (0-1) of ISY Fan running state UOM
            self.setDriver("CLIFRS", int(thermoState["fanstate"]), True, forceReport)
            # translate API schedule part into ISY schedule mode indexed values
            self.setDriver("CLISMD", int(thermoState["schedulepart"]), True, forceReport)
            # set away state from API flag
            self.setDriver("GV1", int(thermoState["away"]), True, forceReport)
            
        else:
            # set thermostat state to offline:
            self.setDriver("GV0", 0, True, force=forceReport) # Thermostat offline

    # update the sensor states and alerts for this thermostat
    def updateSensorsandAlerts(self, forceReport=False):
        
        # get the alert properties for the thermostat
        alertStates = self._conn.getThermostatAlerts() 

        if alertStates:

            # set the default alerts (filter, UV lamp, and service) from the alert info 
            alerts = alertStates["alerts"]
            self.setDriver("GV11", int(next((alert["active"] for alert in alerts if alert["name"] == "Air Filter"), False)), True, forceReport) 
            self.setDriver("GV12", int(next((alert["active"] for alert in alerts if alert["name"] == "UV Lamp"), False)), True, forceReport) 
            self.setDriver("GV13", int(next((alert["active"] for alert in alerts if alert["name"] == "Service"), False)), True, forceReport) 

        # get the state of remote sensors connected to the thermostat
        sensorStates = self._conn.getSensorStates() 

        if sensorStates:

            # spin through the child nodes of this thermostat and update the sensors
            for addr in self.controller.nodes:
    
                # if the device is a sensor node, retrieve the driver values from the sensor State data
                node = self.controller.nodes[addr]
                if node.id == "SENSOR" and node.primary == self.address:

                    # locate the sensor in the sensor states corresponding to the node
                    sensor = next((sensor for sensor in sensorStates["sensors"] if sensor["name"] == node.name), None)
                    if sensor:
                        node.setDriver("ST", float(sensor.get("temp", 0)), True, forceReport)
                        node.setDriver("BATLVL", int(sensor.get("battery", 0)), True, forceReport)
        
        # get the runtimes for the thermostat
        # TO-DO

    # disconnect from the thermostat (close session) and show as offlien
    def disconnect(self):

        # close the session in the connection object
        self._conn.close()

        # set thermostat state to offline:
        self.setDriver("GV0", 0, True, True) # Thermostat offline

    # override getDriver to return the last setDriver() value instead of reading from poly.config
    def getDriver(self, dv):
        return next((driver["value"] for driver in self.drivers if driver["driver"] == dv), None) 
    
    drivers = [
        {"driver": "ST", "value": 0, "uom": ISY_TEMP_F_UOM},
        {"driver": "CLISPH", "value": 0, "uom": ISY_TEMP_F_UOM},
        {"driver": "CLISPC", "value": 0, "uom": ISY_TEMP_F_UOM},
        {"driver": "CLIMD", "value": 0, "uom": ISY_TSTAT_MODE_UOM},
        {"driver": "CLIFS", "value": 0, "uom": ISY_TSTAT_FS_UOM},
        {"driver": "CLIHUM", "value": 0, "uom": ISY_REL_HUMIDITY},
        {"driver": "CLIHCS", "value": 0, "uom": ISY_TSTAT_HCS_UOM},
        {"driver": "CLIFRS", "value": 0, "uom": ISY_TSTAT_FRS_UOM},
        {"driver": "CLISMD", "value": 0, "uom": ISY_INDEX_UOM},
        {"driver": "GV0", "value": 0, "uom": ISY_BOOL_UOM},
        {"driver": "GV11", "value": 0, "uom": ISY_INDEX_UOM},
        {"driver": "GV12", "value": 0, "uom": ISY_INDEX_UOM},
        {"driver": "GV13", "value": 0, "uom": ISY_INDEX_UOM},
    ]
    commands = {
        "BRT": cmd_inc_dec,
        "DIM": cmd_inc_dec,
        "SET_CLISPH": cmd_set_sp,
        "SET_CLISPC": cmd_set_sp,
        "SET_CLIMD": cmd_set_mode,
        "SET_CLIFS": cmd_set_fan,
        "SCHED_ON": cmd_set_sched,
        "SCHED_OFF": cmd_set_sched,
    }

# Controller class
class Controller(polyinterface.Controller):

    id = "CONTROLLER"
    _customData = {}

    def __init__(self, poly):
        super(Controller, self).__init__(poly)
        self.name = "Venstar ColorTouch Nodeserver"

    # Start the node server
    def start(self):

        LOGGER.info("Started Venstar ColorTouch nodeserver...")
      
        # load custom data from polyglot
        self._customData = self.polyConfig["customData"]
        
        # If a logger level was stored for the controller, then use to set the logger level
        level = self.getCustomData("loggerlevel")
        if level is not None:
            LOGGER.setLevel(int(level))

        # load nodes previously saved to the polyglot database
        # Note: has to be done in two passes to ensure thermostat (primary/parent) nodes exist
        # before sensor (child) nodes
        # first pass for thermostat nodes
        for addr in self._nodes:           
            node = self._nodes[addr]
            if node["node_def_id"] in ("THERMOSTAT", "THERMOSTAT_C"):
                
                LOGGER.info("Adding previously saved node - addr: %s, name: %s, type: %s", addr, node["name"], node["node_def_id"])
                self.addNode(Thermostat(self, node["primary"], addr, node["name"]))

        # second pass for sub nodes
        for addr in self._nodes:         
            node = self._nodes[addr]    
            if node["node_def_id"] not in ("CONTROLLER", "THERMOSTAT", "THERMOSTAT_C"):

                LOGGER.info("Adding previously saved node - addr: %s, name: %s, type: %s", addr, node["name"], node["node_def_id"])

                # add sensor nodes
                if node["node_def_id"] == "SENSOR":
                    self.addNode(Sensor(self, node["primary"], addr, node["name"], self.nodes[node["primary"]].tempUnit))

        # Set the nodeserver status flag to indicate nodeserver is running
        self.setDriver("ST", 1, True, True)

        # Report the logger level to the ISY
        self.setDriver("GV20", LOGGER.level, True, True)

    # shutdown the nodeserver on stop
    def stop(self):

        # iterate through the nodes of the nodeserver and disconnect thermostats
        for addr in self.nodes:      
            # ignore the controller node
            if addr != self.address:
                # if the device is a thermostat node, call the disconnect method
                node = self.controller.nodes[addr]
                if node.id in ("THERMOSTAT", "THERMOSTAT_C"):
                    node.disconnect()

        # Set the nodeserver status flag to indicate nodeserver is not running
        self.setDriver("ST", 0, True, True)
    
    # Run discovery for Sony devices
    def cmd_discover(self, command):

        LOGGER.info("Discover devices in cmd_discover()...")
        
        self.discover()

    # Update the profile on the ISY
    def cmd_updateProfile(self, command):

        LOGGER.info("Install profile in cmd_updateProfile()...")
        
        self.poly.installprofile()
        
    # Update the profile on the ISY
    def cmd_setLogLevel(self, command):

        LOGGER.info("Set logging level in cmd_setLogLevel(): %s", str(command))

        # retrieve the parameter value for the command
        value = int(command.get("value"))
 
        # set the current logging level
        LOGGER.setLevel(value)

        # store the new loger level in custom data
        self.addCustomData("loggerlevel", value)
        self.saveCustomData(self._customData)

        # report new value to ISY
        self.setDriver("GV20", value)

    # called every longPoll seconds (default 30)
    def longPoll(self):

        LOGGER.info("Updating alerts and runtimes in longPoll()...")                     
        
        # iterate through the nodes of the nodeserver
        for addr in self.nodes:
        
            # ignore the controller node
            if addr != self.address:

                # if the device is a thermostat node, call the sensors and alerts method
                node = self.controller.nodes[addr]
                if node.id in ("THERMOSTAT", "THERMOSTAT_C"):
                    node.updateSensorsandAlerts()

        # saved any instance variable changes to Polyglot (e.g., temp units)
        self.saveCustomData(self._customData)

    # called every shortPoll seconds
    def shortPoll(self):

        LOGGER.info("Updating node states in shortPoll()...")
        
        # iterate through the nodes of the nodeserver
        for addr in self.nodes:
        
            # ignore the controller node
            if addr != self.address:

                # if the device is a thermostat node, call the update node states method
                node = self.controller.nodes[addr]
                if node.id in ("THERMOSTAT", "THERMOSTAT_C"):
                    node.updateNodeStates()          

    # discover thermostats and SBB devices
    def discover(self):

        self.removeNoticesAll()

        # create an empty array for the thermostat list
        thermostats = []
    
        # Check to see if one or more hostnames were specified in the in custom custom configuration parameters
        customParams = self.polyConfig["customParams"]
        if PARAM_HOSTNAMES in customParams:
            
            dynamicDiscovery = False

            # iterate through hostnames in custom configuration and build an array of thermostats
            hosts = customParams[PARAM_HOSTNAMES].split(";")
            for host in hosts:

                # since we don't have an ID or mac address, build one with the last 4 
                try:
                    id = str(hex(int(IPv4Address(socket.gethostbyname(host)))))[-8:]
                except:                    
                    # add notice that host was resolved
                    LOGGER.warning("Unable to resolve address for specified hostname %s", host)
                    self.addNotice("Unable to resolve address for specified hostname {}. Please check the 'hostname' parameter value in the Custom Configuration Parameters and restart the nodeserver before retrying.".format(host))
                    continue               
                
                # if the id was resolved, add it to the therostat list
                thermostats.append({
                    "id": id,
                    "hostname": host,
                })                    

        else:

            dynamicDiscovery = True

            # Discover thermostats using SSDP
            thermostats.extend(api.discoverThermostats(10, LOGGER))

        # Process each discovered or specified thermostat
        for thermostat in thermostats:

            hostName = thermostat["hostname"]

            # get the relevant info for the thermostat from the API
            thermoInfo = api.getThermostatInfo(hostName, LOGGER)
            
            if thermoInfo:

                LOGGER.info("Discovered thermostat at hostname %s.", hostName)

                # check for minimum API level support
                #if thermoInfo["api_ver"] < api.THERMO_MINIMUM_API_LEVEL:

                # for now only support residential
                if thermoInfo["type"] != api.THERMO_TYPE_RESIDENTIAL:
              
                    # Add a notice to Polyglot dashboard
                    self.addNotice("Thermostat of type {} at hostname {} not supported. Currently only residential thermostats supported.".format(thermoType, hostName))
                    continue

                else:

                    tempUnit = thermoInfo["tempunits"]

                    # check to see if a thermostat node already exists for the thermostat
                    thermostatAddr = getValidNodeAddress(thermostat["id"][-8:])
                    if thermostatAddr not in self.nodes:

                        # get the relevant elements for the thermstat from the returned data
                        thermoName = thermoInfo["name"]
                        thermoType = thermoInfo["type"]

                        # create a thermostat node for the thermostat
                        thermostatNode = Thermostat(self, self.address, thermostatAddr, getValidNodeName(thermoName), hostName, thermoType, tempUnit)
                        self.addNode(thermostatNode)
                    else:
                        thermostatNode = self.nodes[thermostatAddr]

                    # add child nodes for the thermostats sensors
                    n = 0
                    for sensor in thermoInfo["sensors"]:
                        
                        # ignore the "Space Temp" sensor
                        if sensor["name"] != "Space Temp":
                            sensorAddr = getValidNodeAddress(thermostatAddr + "_S" + str(n))
                            self.addNode(Sensor(self, thermostatAddr, sensorAddr, sensor["name"], tempUnit))
                            n += 1

            else:
                # Log a warning and add a notice to Polyglot dashboard
                LOGGER.warning("Unable to query specified hostname %s", hostName)
                if dynamicDiscovery:
                    self.addNotice("Unable to connect to thermostat at hostname {}. Please make sure the thermostat is reachable on your network from your Polyglot server before retrying.".format(hostName))
                else:
                    self.addNotice("Unable to connect to thermostat at hostname {}. Please check the 'hostname' parameter value in the Custom Configuration Parameters and/or that the thermostat is reachable on your network from your Polyglot server before retrying.".format(hostName))

        # send custom data added by new nodes to polyglot
        self.saveCustomData(self._customData)

        # update all driver values for all the discovered thermostats and devices
        for addr in self.nodes:
        
            # ignore the controller node
            if addr != self.address:

                # if the device is a thermostat node, call the updateNodeStates method
                node = self.controller.nodes[addr]
                if node.id in ("THERMOSTAT", "THERMOSTAT_C"):
                    node.updateNodeStates(True)
                    node.updateSensorsandAlerts(True)

    # helper method for storing custom data
    def addCustomData(self, key, data):

        # add specififed data to custom data for specified key
        self._customData.update({key: data})

    # helper method for retrieve custom data
    def getCustomData(self, key):

        # return data from custom data for key
        if key in self._customData:
            return self._customData[key]
        else:
            return None
        
    drivers = [
        {"driver": "ST", "value": 0, "uom": ISY_BOOL_UOM},
        {"driver": "GV20", "value": 0, "uom": ISY_INDEX_UOM}
    ]
    commands = {
        "DISCOVER": cmd_discover,
        "UPDATE_PROFILE" : cmd_updateProfile,
        "SET_LOGLEVEL": cmd_setLogLevel
    }

# Removes invalid charaters and lowercase ISY Node address
def getValidNodeAddress(s):

    # remove <>`~!@#$%^&*(){}[]?/\;:"' characters
    addr = re.sub(r"[<>`~!@#$%^&*(){}[\]?/\\;:\"']+", "", s)

    return addr[-14:].lower()

# Removes invalid charaters for ISY Node description
def getValidNodeName(s):

    # remove <>`~!@#$%^&*(){}[]?/\;:"' characters from names
    return re.sub(r"[<>`~!@#$%^&*(){}[\]?/\\;:\"']+", "", s)

# Main function to establish Polyglot connection
if __name__ == "__main__":
    try:
        polyglot = polyinterface.Interface()
        polyglot.start()
        control = Controller(polyglot)
        control.runForever()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.warning("Received interrupt or exit...")
        polyglot.stop()
    except Exception as err:
        LOGGER.error('Excption: {0}'.format(err), exc_info=True)
        sys.exit(0)