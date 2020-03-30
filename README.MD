# VenstarCT-polyglotv2
A NodeServer for Polyglot v2 that interfaces to the Venstar ColorTouch series of thremostats through a local API. See https://venstar.com/thermostats/colortouch/.

### Instructions for local Polyglot-V2 installation:

1. Install the VenstarCT nodeserver from the Polyglot Nodeserver Store.
2. Log into the Polyglot Dashboard (https://<Polyglot Server IP Address>:3000)
3. Add the VenstarCT nodeserver as a Local (Co-Resident with Polyglot) nodeserver type.
4. Once the "Venstar ColorTouch NodeServer" node appears in ISY994i Adminstative Console, click "Discover Devices" to load nodes for each of the thermostats found on the local network. THIS PROCESS WILL TAKE AT LEAST 10 SECONDS, depending on the number of thermostats you have, so please be patient before retrying. Also, please check the Polyglot Dashboard for messages regarding Discover Devices failure conditions.

### Notes:

1. Currently only residential ColorTouch thermostats (T7800, T7850, and T7900) are supported.
2. The nodeserver relies on polling of the Venstar ColorTouch thermostats, so there may be some latency (up to shortPoll seconds) for reflections of changes in state.
3. All thermostats will get at least one child node for a sensor labeled "Thermostat." If you don't have any other remote sensors, this is redundant, and it will be removed in a future version.
4. If a thermostat control rule is violated, like setting the heat and cool setpoint too close to each other in Auto mode or trying to change fan mode or setpoints when in Away mode, a warning is logged in the log and the command is ignored. There is currently no way to send such warning or error messages back to the ISY.

For more information regarding this Polyglot Nodeserver, see https://forum.universal-devices.com/topic/29395-polyglot-venstar-colortouch-nodeserver/.