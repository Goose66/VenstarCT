#!/usr/bin/env python
"""
Python wrapper class for Venstar ColorTouch thermostat API
by Goose66 (W. Randy King) kingwrandy@gmail.com
"""

import sys
import logging 
import requests
import ssdp
from urllib.parse import unquote, urlparse

# Configure a module level logger for module testing
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

# Venstar ColorTouch Local REST API v4 spec.
_API_HTTP_HEADERS = {}
_API_GET_API_INFO = {
    "url": "http://{host_name}/",
    "method": "GET"
}
_API_GET_THERMOSTAT_INFO = {
    "url": "http://{host_name}/query/info",
    "method": "GET"
}
_API_GET_SENSOR_INFO = {
    "url": "http://{host_name}/query/sensors",
    "method": "GET"
}
_API_GET_RUNTIMES = {
    "url": "http://{host_name}/query/runtimes",
    "method": "GET"
}
_API_GET_ALERTS = {
    "url": "http://{host_name}/query/alerts",
    "method": "GET"
}
_API_SET_CONTROL = {
    "url": "http://{host_name}/control",
    "method": "POST"
}
_API_SET_SETTINGS = {
    "url": "http://{host_name}/settings",
    "method": "POST"
}

_SSDP_SEARCH_TARGET = "colortouch:ecp"

THERMO_TYPE_RESIDENTIAL = "residential"
THERMO_TYPE_COMMERCIAL = "commercial"

THERMO_MINIMUM_API_LEVEL = 4

THERMO_SETTING_TEMP_UNITS = "tempunits"
THERMO_SETTING_AWAY_STATE = "away"
THERMO_SETTING_SCHEDULE_STATE = "schedule"
THERMO_SETTING_HUMIDIFY_SETPOINT = "hum_setpoint"
THERMO_SETTING_DEHUMIDIFY_SETPOINT = "dehum_setpoint"

THERMO_SCHED_PART_INACTIVE = 255

# constants for mode
THERMO_MODE_OFF = 0
THERMO_MODE_HEAT = 1
THERMO_MODE_COOL = 2
THERMO_MODE_AUTO = 3

# Timeout durations for HTTP calls - defined here for easy tweaking
_HTTP_GET_TIMEOUT = 6.05
_HTTP_POST_TIMEOUT = 4.05

# interface class for a particular Venstart ColorTouch thermostat
class thermostatConnection(object):

    _hostname = ""
    _pin = ""
    _session = None
    _logger = None

    # Primary constructor method
    def __init__(self, hostname, pin="", logger=_LOGGER):

        self._hostname = hostname
        self._pin = pin
        self._logger = logger

        # open an HTTP session
        self._session = requests.Session()

    # Call the specified REST API
    def _call_api(self, api, params=None):
      
        method = api["method"]
        url = api["url"].format(host_name = self._hostname)

        # uncomment the next line to dump HTTP request data to log file for debugging
        self._logger.debug("HTTP %s data: %s", method + " " + url, params)

        try:
            response = self._session.request(
                method,
                url,
                params = params, 
                headers = _API_HTTP_HEADERS, # same every call     
                timeout= _HTTP_POST_TIMEOUT if method == "POST" else _HTTP_GET_TIMEOUT
            )
            
            # raise any codes other than 200, 201, and 401 for error handling 
            if response.status_code not in (200, 201, 401):
                response.raise_for_status()

        # Allow timeout and connection errors to be ignored - log and return false
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            self._logger.warning("HTTP %s in _call_api() failed: %s", method, str(e))
            return False
        except:
            self._logger.error("Unexpected error occured: %s", sys.exc_info()[0])
            raise

        # uncomment the next line to dump HTTP response to log file for debugging
        self._logger.debug("HTTP response code: %d data: %s", response.status_code, response.text)

        return response

    # Get state information for the thermostat
    def getThermostatState(self):
        """Returns the current state of the thermostat
        NOTE: For polling, calls all of the query APIS for the thermostat

        Returns:
        dictionary of state properties for the thermostat
        """

        self._logger.debug("in API getThermostatState()...")

        # call the session API with the parameters
        response  = self._call_api(_API_GET_THERMOSTAT_INFO)
        
        # if data returned, also retrieve the sensor state
        if response and response.status_code == 200:

            # get the state data
            respData = response.json()
    
            # get state of alerts
            response  = self._call_api(_API_GET_ALERTS)

            # if data returned, add the alert states to the state properties
            if response and response.status_code == 200:

                for alert in response.json()["alerts"]:
                    name = alert["name"].replace(" ","").lower() + "alert"
                    value = alert["active"]
                    respData.update({name: value})
                                    
            return respData
            
        # otherwise return error (False)
        else:
            return False

    # Get the temps from the remote sensors
    def getSensorState(self):
        """Returns the temps from the sensors

        Returns:
        dictionary of state properties for sensors
        """

        self._logger.debug("in API getSensorState()...")
        
        # get the temperature sensor state
        response  = self._call_api(_API_GET_SENSOR_INFO)

        # if data returned, add the sensor states to the state properties
        if response and response.status_code == 200:
            return response.json()
            
        # otherwise return error (False)
        else:
            return False

    # Toggle the state of a pump or heater - returns system state information
    def setThermostatControls(self, mode=None, fan=None, heattemp=None, cooltemp=None):
        """Set the control modes and setpoints for the thermostat

        Parameters:
        mode -- thermostat mode: 0-Off, 1-Heat, 2-Cool, 3-Auto
        fan -- fan mode: 0-Auto, 1-On
        heattemp -- heat to temperature
        cooltemp -- cool to temperature
        Returns:
        boolean indicating success
        """

        self._logger.debug("in API setThermostatControls()...")
       
        # format url parameters
        params = {}
        if mode is not None:
            params.update({"mode": mode})
        if fan is not None:
            params.update({"fan": fan})
        if heattemp is not None:
            params.update({"heattemp": heattemp})
        if cooltemp is not None:
           params.update({"cooltemp": cooltemp})

        # call the control API with the specified parameters
        response  = self._call_api(_API_SET_CONTROL, params=params)
        
        if response and response.status_code == 200:

            # check response for API error and log and return False if present
            respData = response.json()
            if "error" in respData:
                self._logger.warning("Error message returned from control API: %s", respData["reason"])
                return False
            
            # other return True
            else:
                return True

        # otherwise return False to indicate previously logged failure
        else:
            return False

    # Toggle the state of a pump or heater - returns system state information
    def setThermostatSettings(self, setting, value):
        """Sets specific setting for the thermostat

        Parameters:
        setting -- setting to adjust:
            THERMO_SETTING_TEMP_UNITS - thermostat temperature units: 0-F, 1-C
            THERMO_SETTING_AWAY_STATE - away state: 0-Home, 1-Away
            THERMO_SETTING_SCHEDULE_STATE - schedule state: 0-off, 1-On
            THERMO_SETTING_HUMIDIFY_SETPOINT - humidify setpoint: 0-60%
            THERMO_SETTING_DEHUMIDIFY_SETPOINT = dehumidify setpoint: 25-99%
        value -- new value for setting
        Returns:
        boolean indicating success
        """

        self._logger.debug("in API setThermostatSettings()...")
       
        # format url parameters
        params = {
           setting: value
        } 

        # call the settings API with the specified parameters
        response  = self._call_api(_API_SET_SETTINGS, params=params)

        print(response.text)

        if response and response.status_code == 200:
    
            # check response for API error and log and return False if present
            respData = response.json()
            if "error" in respData:
                self._logger.warning("Error message returned from settings API: %s", respData["reason"])
                return False
            
            # other return True
            else:
                return True

        # otherwise return False to indicate previously logged failure
        else:
            return False

    # close any HTTP session
    def close(self):
        self._session.close()
            
def getThermostatInfo(hostName, logger=_LOGGER):
    """Make call to check thermostat and receive API info - for external calling

    Parameters:
    hostName -- host name or IP address of thermostat
    Returns:
    dictionary of API properties for the thermostat or False if error occurred
    """

    logger.debug("in getThermostatInfo()...")

    try:
        # Call the REST API to get the api version info
        response = requests.request(_API_GET_API_INFO["method"],
            _API_GET_API_INFO["url"].format(host_name = hostName),
            headers = _API_HTTP_HEADERS, # same every call     
            timeout= _HTTP_GET_TIMEOUT
        )

        # raise anything other than a successful (200) HTTP code to error handling
        response.raise_for_status()

    # For errors that may indicate a bad hostName, log a warning and return false
    except(requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
        logger.warning("HTTP GET in getThermostatInfo() failed: %s", str(e))
        return False
    except:
        logger.exception("Unexpected error from HTTP call in getThermostatInfo(): %s", sys.exc_info()[0])
        raise
    
    thermostatInfo = response.json()

    # get remaining thermostat info from the thermostat state API 
    try:
        # Call the REST API to get the api version info
        response = requests.request(
            _API_GET_THERMOSTAT_INFO["method"],
            _API_GET_THERMOSTAT_INFO["url"].format(host_name = hostName),
            headers = _API_HTTP_HEADERS, # same every call     
            timeout= _HTTP_GET_TIMEOUT
        )

        # raise anything other than a successful (200) HTTP code to error handling
        response.raise_for_status()

    # For errors that may indicate a bad hostName, log a warning and return false
    except(requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
        logger.warning("HTTP GET in getThermostatInfo() failed: %s", str(e))
        return False
    except:
        logger.exception("Unexpected error from HTTP call in getThermostatInfo(): %s", sys.exc_info()[0])
        raise
    
    # add the additional info
    thermostatInfo.update(response.json())

    # return the thermostat info
    return thermostatInfo
   
# discover devices 
def discoverThermostats(timeout=5, logger=_LOGGER):
    """Discover thermostats on the network supporting the Venstar ColorTouch API
        
    Parameters:
    timeout -- timeout for SSDP broadcast (defaults to 5)
    logger -- logger to use for errors 
    """

    thermostats = []

    # discover devices via the SSDP M-SEARCH method
    responses = ssdp.discover(_SSDP_SEARCH_TARGET, timeout=timeout)

    logger.debug("SSDP discovery returned %i thermostats.", len(responses))

    # iterate through the responses 
    for response in responses:

        logger.debug("Thermostat found in discover - USN: %s, Location: %s", response.usn, response.location)

        # parse out the id, name, type, and hostname from the response 
        usn = response.usn
        tID = usn[usn.find("ecp:") + 4:usn.find(":name")].replace(":", "")
        tName = unquote(usn[usn.find("name:") + 5:usn.find(":type")])
        tType = usn[usn.find("type:") + 5:]
        tHostName = urlparse(response.location).netloc
        thermostatInfo = {
            "id": tID,
            "name": tName,
            "type": tType,
            "hostname": tHostName
        }

        # append to thermostat list
        thermostats.append(thermostatInfo)

    return thermostats
