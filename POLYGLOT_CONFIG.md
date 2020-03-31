## VenstarCT NodeServer Configuration
####Advanced Configuration:
- key: shortPoll, value: polling interval for thermostat states on the local network in seconds (defualt 10)
- key: longPoll, value: polling interval for alerts, sensor states, and runtimes in seconds (default 60)

####Custom Configuration Parameters:
- key: hostname, value: hostname(s) or IP address(es) for thermostat(s), seperated by semicolons, to bypass SSDP discovery (optional)
- key: pin, value: PIN code for thermostats if in screen lock mode (PIN not implemented yet) (optional)