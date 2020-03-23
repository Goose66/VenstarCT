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
ISY_TEMP_F_UOM = 17 # UOM for temperatures (farenheit)
ISY_TEMP_C_UOM = 4 # UOM for temperatures (celcius)
ISY_REL_HUMIDITY = 22 # UOM for relative humidity (percent)
ISY_THERMO_MODE_UOM = 67 # UOM for thermostat mode
ISY_THERMO_HCS_UOM = 66 # UOM for thermostat heat/cool state
ISY_THERMO_FS_UOM = 68 # UOM for fan mode
ISY_THERMO_FRS_UOM = 80 # UOM for fan runstate

# values for operation mode
IX_SYS_OPMODE_OFF = 0
IX_SYS_OPMODE_POOL = 1
IX_SYS_OPMODE_SPA = 2
IX_SYS_OPMODE_SERVICE = 3
IX_SYS_OPMODE_UNKNOWN = 4

# values for driver device state
IX_DEV_ST_UNKNOWN = -1
IX_DEV_ST_OFF = 0
IX_DEV_ST_ON = 1
IX_DEV_ST_ENABLED = 3

# custom parameter values for this nodeserver
PARAM_HOSTNAMES = "hostname"
PARAM_PIN = "pin"

# Node class for thermostat
class Thermostat(polyinterface.Node):

    id = "THERMOSTAT"
    hint = [0x01, 0x0C, 0x01, 0x00] # Residential/HVAC/Thermostat
    _hostName = ""
    _type = ""
    _tempUnit = 0
    _conn = None
    
    # Override init to handle temp units
    def __init__(self, controller, primary, addr, name, hostName=None, type=None, tempUnit=None):
        super(Thermostat, self).__init__(controller, primary, addr, name)

        # make the thermostat a primary node
        # Note: this is for future child nodes, e.g., sensors
        self.isPrimary = True

        if hostName is None:
        
            # retrieve the thermostat properties from polyglot custom data
            cData = self.controller.getCustomData(addr).split(";")
            self._hostName = cData[0]
            self._type = cData[1]
            self._tempUnit = cData[2]

        else:
            self._hostName = hostName
            self._type = type
            self._tempUnit = tempUnit

        # setup the temperature unit for the node
        # this method updates the custom data for the node
        self.setTempUnit(self._tempUnit)

        # create a connection object in the API for the the thermostat 
        self._conn = api.thermostatConnection(self._hostName, logger=LOGGER)

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

        self._tempUnit = tempUnit

        # store instance variables in polyglot custom data
        cData = ";".join([
            self._hostName,
            self._type,
            str(self._tempUnit),
        ])
        self.controller.addCustomData(self.address, cData)

    # Increase/decrease the active setpoint by one degree
    def cmd_inc_dec(self, command):

        LOGGER.info("Increase or decrease temperature of %s in command handler: %s.", self.name, str(command))

        # update the driver values for the thermostat since we are incrementing setpoints
        self.updateNodeStates()

        # if the thermostat is online
        if int(self.getDriver("GV0")):
    
            # get the current thermostat settings
            sph = float(self.getDriver("CLISPH"))
            spc = float(self.getDriver("CLISPC"))
            mode = int(self.getDriver("CLIMD"))

            # determine the setpoint to increase based on the mode
            if mode == api.THERMO_MODE_OFF:
                LOGGER.warning("Setpoint(s) not adjusted for thermostat in Off mode.")
                return
            if mode in (api.THERMO_MODE_HEAT, api.THERMO_MODE_AUTO):
                if command["cmd"] == "BRT":
                    sph += 1.0
                else:
                    sph -= 1.0
            if mode in (api.THERMO_MODE_COOL, api.THERMO_MODE_AUTO):
                if command["cmd"] == "BRT":
                    spc += 1.0
                else:
                    spc -= 1.0

            #TO-DO: can't change settings while in away mode

            # call the controls API to set the new setpoints
            if self._conn.setThermostatControls(heattemp=sph, cooltemp=spc):
                self.setDriver("CLISPH", sph)
                self.setDriver("CLISPC", spc)

            else:
                LOGGER.error("Call to API setThermostatControls() failed in %s command handler.", command["cmd"])

    # Set the thermostat heat setpoint to the specified value
    def cmd_set_sp(self, command):

        LOGGER.info("Set the setpoints for %s in command handler: %s", self.name, str(command))

        # update the driver values for the thermostat since we have to specify both setpoint values
        self.updateNodeStates()

        # if the thermostat is online
        if int(self.getDriver("GV0")):

            # set the setpoints based on the command 
            if command["cmd"] == "SET_CLISPH":
                spc = float(self.getDriver("CLISPC"))
                sph = float(command["value"])
            else:
                sph = float(self.getDriver("CLISPH"))
                spc = float(command["value"])

            #TO-DO: maker sure spc > sph by setpointdelta degrees if in auto mode
            #TO-DO: can't change settings while in away mode

            # call the controls API to set the new setpoints
            if self._conn.setThermostatControls(heattemp=sph, cooltemp=spc):
                self.setDriver("CLISPH", sph)
                self.setDriver("CLISPC", spc)

            else:
                LOGGER.error("Call to API setThermostatControls() failed in %s command handler.", command["cmd"])

    # Set the thermostat mode to the specified value
    def cmd_set_mode(self, command):

        LOGGER.info("Set the thermostat mode for %s in command handler: %s", self.name, str(command))

        # update the driver values for the thermostat since we have to specify both setpoint values
        self.updateNodeStates()

        # if the thermostat is online
        if self.getDriver("GV0"):

            # get the current thermostat settings
            sph = float(self.getDriver("CLISPH"))
            spc = float(self.getDriver("CLISPC"))
            
            mode = int(command.get("value"))

            #TO-DO: can't change settings while in away mode

            # call the controls API to set the thermostat mode
            if self._conn.setThermostatControls(mode=mode, heattemp=sph, cooltemp=spc):
                self.setDriver("CLIMD", mode)

            else:
                LOGGER.error("Call to API setThermostatControls() failed in SET_CLIMD command handler.")

    # Set the thermostat mode to the specified value
    def cmd_set_fan(self, command):

        LOGGER.info("Set the fan mode for %s in command handler: %s", self.name, str(command))

        fan = int(command.get("value"))    

        #TO-DO: can't change settings while in away mode

        # call the controls API to set fan mode
        if self._conn.setThermostatControls(fan=fan):
            self.setDriver("CLIFS", fan)

        else:
            LOGGER.error("Call to API setThermostatControls() failed in SET_CLIFS command handler.")

    # Set the thermostat to away mode
    def cmd_set_away_on(self, command):

        LOGGER.info("Set %s to away mode in AWAY_ON command handler.", self.name)

        # call the settings API to set the away mode
        if self._conn.setThermostatSettings(api.THERMO_SETTING_AWAY_STATE, 1):
            self.setDriver("GV1", 1)

        else:
            LOGGER.error("Call to API setThermostatSettings() failed in SET_AWAY_ON command handler.")

    # Set the thermostat to home mode (away mode off)
    def cmd_set_away_off(self, command):
    
        LOGGER.info("Set %s to home mode in AWAY_OFF command handler.", self.name)

        # call the settings API to set the away mode
        if self._conn.setThermostatSettings(api.THERMO_SETTING_AWAY_STATE, 0):
            self.setDriver("GV1", 0)

        else:
            LOGGER.error("Call to API setThermostatSettings() failed in SET_AWAY_OFF command handler.")

    # Set the schedule mode on
    def cmd_set_sched_on(self, command):
    
        LOGGER.info("Set schedule mode on for %s in SCHED_ON command handler.", self.name)

        # call the settings API to set the schedule mode
        if self._conn.setThermostatSettings(api.THERMO_SETTING_SCHEDULE_STATE, 1):
            
            # we have to update states to get the current schedule part
            self.updateNodeStates()

        else:
            LOGGER.error("Call to API setThermostatSettings() failed in SET_SCHED_ON command handler.")

    # Set the schedule mode off
    def cmd_set_sched_off(self, command):
    
        LOGGER.info("Set schedule mode off for %s in SCHED_OFF command handler.", self.name)

        # call the settings API to set the sechdule mode
        if self._conn.setThermostatSettings(api.THERMO_SETTING_SCHEDULE_STATE, 0):
            
            # update the schedule part to inactive
            self.setDriver("CLISMD", api.THERMO_SCHED_PART_INACTIVE)

        else:
            LOGGER.error("Call to API setThermostatSettings() failed in SET_SCHED_OFF command handler.")

    # update the state this thermostat
    def updateNodeStates(self, forceReport=False):
        
        # get the thermostat state from the API
        thermoState = self._conn.getThermostatState() 

        if thermoState:

            # set thermostat state to offline:
            self.setDriver("GV0", 1, True, forceReport) # Thermostat online

            # if the tempunits has changed, fix the node
            if thermoState["tempunits"] != self._tempUnit:
                self.setTempUnit(thermoState["tempunits"])

            # udpate the remaining driver values
            self.setDriver("ST", float(thermoState["spacetemp"]), True, forceReport)
            self.setDriver("CLISPH", float(thermoState["heattemp"]), True, forceReport)
            self.setDriver("CLISPC", float(thermoState["cooltemp"]), True, forceReport)
            self.setDriver("CLIHUM", float(thermoState["hum"]), True, forceReport)
             # API thermostat mode translates directly to first four values (0-4) of ISY Thermostat mode UOM
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
            # set the default alerts from the state info (can these change?)
            self.setDriver("GV11", int(thermoState["airfilteralert"]), True, forceReport) 
            self.setDriver("GV12", int(thermoState["uvlampalert"]), True, forceReport) 
            self.setDriver("GV13", int(thermoState["servicealert"]), True, forceReport) 

        else:
            # set thermostat state to offline:
            self.setDriver("GV0", 0, True, force=forceReport) # Thermostat offline

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
        {"driver": "CLIMD", "value": 0, "uom": ISY_THERMO_MODE_UOM},
        {"driver": "CLIFS", "value": 0, "uom": ISY_THERMO_FS_UOM},
        {"driver": "CLIHUM", "value": 0, "uom": ISY_REL_HUMIDITY},
        {"driver": "CLIHCS", "value": 0, "uom": ISY_THERMO_HCS_UOM},
        {"driver": "CLIFRS", "value": 0, "uom": ISY_THERMO_FRS_UOM},
        {"driver": "CLISMD", "value": 0, "uom": ISY_INDEX_UOM},
        {"driver": "GV0", "value": 0, "uom": ISY_BOOL_UOM},
        {"driver": "GV1", "value": 0, "uom": ISY_INDEX_UOM},
        {"driver": "GV11", "value": 0, "uom": ISY_BOOL_UOM},
        {"driver": "GV12", "value": 0, "uom": ISY_BOOL_UOM},
        {"driver": "GV13", "value": 0, "uom": ISY_BOOL_UOM},
    ]
    commands = {
        "BRT": cmd_inc_dec,
        "DIM": cmd_inc_dec,
        "SET_CLISPH": cmd_set_sp,
        "SET_CLISPC": cmd_set_sp,
        "SET_CLIMD": cmd_set_mode,
        "SET_CLIFS": cmd_set_fan,
        "AWAY_ON": cmd_set_away_on,
        "AWAY_OFF": cmd_set_away_off,
        "SCHED_ON": cmd_set_sched_on,
        "SCHED_OFF": cmd_set_sched_off,
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
                # TO-DO

        # Set the nodeserver status flag to indicate nodeserver is running
        self.setDriver("ST", 1, True, True)

        # Report the logger level to the ISY
        self.setDriver("GV20", LOGGER.level, True, True)
 
        # update the driver values of all nodes (force report)
        self.updateNodeStates(True)

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

        pass

    # called every shortPoll seconds (default 10)
    def shortPoll(self):

        # update the state values for thermostats
        LOGGER.info("Updating node states in shortPoll()...")
        self.updateNodeStates()          

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
    
                    # check to see if a thermostat node already exists for the thermostat
                    thermostatAddr = getValidNodeAddress(thermostat["id"][-8:])
                    if thermostatAddr not in self.nodes:

                        # get the relevant elements for the thermstat from the returned data
                        thermoName = thermoInfo["name"]
                        tempUnits = thermoInfo["tempunits"]
                        thermoType = thermoInfo["type"]

                        # create a thermostat node for the thermostat
                        node = Thermostat(self, self.address, thermostatAddr, getValidNodeName(thermoName), hostName, thermoType, tempUnits)
                        self.addNode(node)
                    
            else:
                # Log a warning and add a notice to Polyglot dashboard
                LOGGER.warning("Unable to query specified hostname %s", hostName)
                if dynamicDiscovery:
                    self.addNotice("Unable to connect to thermostat at hostname {}. Please make sure the thermostat is reachable on your network from your Polyglot server before retrying.".format(hostName))
                else:
                    self.addNotice("Unable to connect to thermostat at hostname {}. Please check the 'hostname' parameter value in the Custom Configuration Parameters and/or that the thermostat is reachable on your network from your Polyglot server before retrying.".format(hostName))

        # send custom data added by new nodes to polyglot
        self.saveCustomData(self._customData)

        # update the driver values for the discovered thermostats and devices (force report)
        self.updateNodeStates(True)

    # update the node states for all thermostats
    def updateNodeStates(self, forceReport=False):

        LOGGER.debug("Polling all thermostats in updateNodeState()...")
        
        # iterate through the nodes of the nodeserver
        for addr in self.nodes:
        
            # ignore the controller node
            if addr != self.address:

                # if the device is a thermostat node, call the updateNodeStates method
                node = self.controller.nodes[addr]
                if node.id in ("THERMOSTAT", "THERMOSTAT_C"):
                    node.updateNodeStates(forceReport)

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