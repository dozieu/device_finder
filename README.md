#device_finder
==============
Locates the switch ip address and port on which a device is connected to within a Cisco Layer 2 environment.

Overview
==========
This python script employs the Netmiko Library with textfsm and ntc-templates to perform a Layer 2 trace in a Cisco switch network.
Script will accept login credentials, the IP and MAC addresses of the device to find and is able to use these input to locate 
the edge switch and port to which the device is connected. 
A use case for this would be to find the switch and port to which a Cisco IP phone is connected to within a building. It is able to do this within a network of NXOS and IOS network devices. script results also represent a physical path to the device being traced.
The script prints the last hop (Ip address) and port on which the device was learnt, and a list of hops along its trace path. 

script can be run with command line arguments

    usage: device_finder.py [-h] [-s str] [-d str] [-m str]

    Locates the switch IP address and port on which a device is connected to within a Cisco
    Layer 2 environment

    optional arguments:
      -h, --help            show this help message and exit
      -s str, --stg_address str
                            starting host address (default: None)
      -d str, --dst_address str
                            destination device address (default: None)
      -m str, --mac_address str
                            destination MAC address [xxxx.xxxx.xxxx] (default: None)
                        
 If not run with cli arguments script will default to presenting prompts to guide user

How it does it
==============
Starts by logging into a Starting switch and checking the CAM tables for mac address and port information 
If the port is a physical port, it notes this and uses CDP to perform a check to verify if device on physical port is a Switch.
If it is a switch this script will log into it and perform the process again till it finds a connected device that is not a switch.
It is able to achieve this by toggling Netmiko Parameters 'device_type' and 'use_textfsm' when sending commands
It is able to hop between IOS and NXOS switches and will stop when it encounters non ios or nxos devices e.g. WLC
It is able to detect a loop in its path and quit. 
Information on netmiko https://github.com/ktbyers/netmiko/blob/develop/README.md

Requirements
============
SSH must be enabled on switches

CDP must be enabled across the L2 network

User account must have enable priviliges on all switches in network

Be sure to enter the correct OS type for your starting switch, if not CDP check will not work 

Must have ntc-templates folder in directory with script. Instructions to install https://github.com/networktocode/ntc-templates


Caveats and known Issues
===============================
- Script performs ping using the default IP address of the starting host.

- When neighbor is on a port channel interface, the first physical port in port group is used to identify connected neighbor.

- Support for LLDP

- Some input Validation

