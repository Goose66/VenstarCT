# VenstarCT-polyglotv2
A NodeServer for Polyglot v2 that interfaces to the Venstar ColorTouch series of thremostats through a local API. See https://venstar.com/thermostats/colortouch/.

### Instructions for local Polyglot-V2 installation:

1. Install the VenstarCT nodeserver from the Polyglot Nodeserver Store.
2. Log into the Polyglot Dashboard (https://<Polyglot Server IP Address>:3000)
3. Add the VenstarCT nodeserver as a Local (Co-Resident with Polyglot) nodeserver type.
4. Once the "Venstar ColorTouch NodeServer" node appears in ISY994i Adminstative Console, click "Discover Devices" to load nodes for each of the thermostats found on the local network. THIS PROCESS MAY TAKE SEVERAL SECONDS depending on the number of thermostats you have, so please be patient and wait 30 seconds or more before retrying. Also, please check the Polyglot Dashboard for messages regarding Discover Devices failure conditions.

### Notes:

1. The nodeserver relies on polling of the Venstar ColorTouch thermostats, so there may be some latency (up to shortPoll seconds) for reflections of changes in state.

For more information regarding this Polyglot Nodeserver, see https://forum.universal-devices.com/topic/28463-polyglot-bond-bridge-nodeserver/.