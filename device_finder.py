#!/usr/bin/env python3

import os
import getpass
import pprint
from datetime import datetime
import pyinputplus as pyip
from netmiko import ConnectHandler, file_transfer
from ntc_templates.parse import parse_output
import re
import argparse



os.environ["NET_TEXTFSM"] = "./ntc-templates/templates/"


def get_args():
    """get command-line arguments"""

    parser = argparse.ArgumentParser(
        description='Locates the switch IP address and port on which a device is connected to within a Cisco Layer 2 environment',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('-s',
                        '--stg_address',    
                        help='starting host address',
                        metavar='str',
                        type=str)

    parser.add_argument('-d',
                        '--dst_address',
                        help='destination device address',
                        metavar='str',
                        type=str)

    parser.add_argument('-m',
                        '--mac_address',
                        help='destination MAC address [xxxx.xxxx.xxxx]',
                        metavar='str',
                        type=str)

    
    return parser.parse_args()



def output_sieve(ios_response):
    ''' Accepts lines and returns list of each line's result of the split method performed on it'''
    output_l = []
    for line in ios_response.splitlines():
        splt_line = line.split()
        output_l.append(splt_line)
    
    return output_l


def port_str_splitter(portstring):
    '''Used to seperate port type and port number from portstring '''
    port_str = (re.findall(r'(\w+?)(\d+)', portstring)[0])[0]
    str_len = len(port_str)
    port_num = portstring[str_len:]
    port_str_split = [port_str, port_num]
    return port_str_split


def physical_port(os_response):
    ''' Returns first physical port from portchannel check response'''
    member_ports = (os_response.split(':')[-1]).split()
    phy_port = member_ports[0]
    return phy_port


def check_dev(host_ip, dst_ip, dst_mac, param, os_type):
    ''' Accesses a host, performs a ping test to the destination then checks for the mac address on the host.
    if it finds the mac address it notes the interface on which it was found. if interface is a portchannel,
    it will retrieve a physical port member. It will then do  a cdp check. 
    function returns [host IP, destination IP, port of next hop, and the output from show cdp neighbor detail]'''

    param['host'] = host_ip
    param['device_type'] = os_type
    port_info = ''

    try:
        output = ''  # perform ping for reachability and mac table refresh,
        net_connect = ConnectHandler(**param)
        output = net_connect.send_command(f'ping {dst_ip}', strip_prompt=True,
                                          strip_command=True, use_textfsm=False)
        
        if '!' in output or '64' in output:

            print(f'{host_ip} pinged... {dst_ip}\n')
            output = ''  # if valid ping response, performs mac address search.
            output += net_connect.send_command(f'show mac address-table | i {dst_mac}', strip_prompt=True,
                                               strip_command=True, use_textfsm=False)
            
            if output:  # if valid mac results, grab port information and check for portchannel membership
                
                locating_info = output_sieve(output)
                
                port_info = locating_info[0][-1]    # -- set port info
                
                print(f'MAC was found on interface {port_info}\n')
                output = ''
                output += net_connect.send_command(f'sho interface {port_info} | i Members', strip_prompt=True,
                                                   strip_command=True, use_textfsm=False)
                if output:  # if portchannel, get a physical interface
                    port_info = physical_port(output)
                else:
                    output = (f' Physical port: {port_info}')
            else:
                print(f'Did not find MAC {dst_mac} in table\n')
                output = ''

        else:
            print(f'Unable to reach device {dst_ip} from starting host'+'\n')
            output = ''

        if output:
            # -- Displays port to check and test cdp information            
            print(f'Checking CDP for port: {port_info}\n')
            output = ''
            output = net_connect.send_command('show cdp neighbors detail', strip_prompt=True,
                                              strip_command=True, use_textfsm=True)
            net_connect.disconnect()

    except IndexError: # occurs when netmiko timers are shorter
        print('output_sieve err: may need to adjust delay factor')

    except Exception as exc:
        print('check_dev err: error device information')        
        print(exc)

    return (host_ip, dst_ip, port_info, output)


def cdp_matcher(host_ip, dst_ip, port_info, output):
    ''' function will seperate the strings that represent port number and port type from the port string. 
    This is because the port string is represented differently for the two commands; 
    the port string is an abbrevieted representation when gotten from [show mac address-table]
    but is complete when gotten from [show cdp neighbors detail].
    we match these by comparing the first two strings that represent the port type 
    and the integer portion of the port string that represents the port number.
    function returns a list with [IP of next hop, end search trigger, OS of next hop] '''

    found_ip, end_search, found_os = 'N/A', False, 'N/A'
    found_neighbor = [found_ip, end_search, found_os]
    port_type = (port_info[:2])
    port_num = (port_str_splitter(port_info))[1]
    for cdp_info in output:
        # Searches through result of show cdp neigbors detail to find IP,OS, and Capabilities
        local_port_num = (cdp_info['local_port']).split('net')
        if port_type == cdp_info['local_port'][:2] and local_port_num[1] == port_num:  # if matched interface

            found_port = cdp_info['local_port']
            if ('management_ip') in cdp_info:  # Set found_ip
                found_ip = cdp_info['management_ip']
            if ('mgmt_ip') in cdp_info:
                found_ip = cdp_info['mgmt_ip']
            if ('software_version') in cdp_info:   # Set found_os
                found_os = cdp_info['software_version']
            if ('version') in cdp_info:
                found_os = cdp_info['version']

            if cdp_info['capabilities'] == 'Host':  # -- In case you encounter other devices e.g. Cisco WLC
                print(
                    f'** Non-switch detected - Unable to trace beyond {host_ip}')
                end_search = True

            if dst_ip == found_ip:  # Stop if IP matches destination IP
                print(
                    f'** Device is CDP enabled and found on {host_ip} {found_port}')
                end_search = True
            break
    else: # No cdp match, last hop is this device
        print(f'** No CDP info. Last hop is: {host_ip} port {port_info}')
        end_search = True

    found_neighbor = [found_ip, end_search, found_os]
    return found_neighbor


def finder(starting_host, dev_addr, dev_mac, dev_param, os_type):
    ''' finder uses the results from check_dev to know whether to jump to next device.
    It checks whether to end search or if to update "os_type" and "starting_host" for next call to check_dev.
    Function returns a list of hops showing the layer 2 path'''

    
    print(f'\nStarting from {starting_host}\n')
    hops = [starting_host]
    ports = []

    while True:
        if starting_host == 'N/A':
            break
        dev_results = check_dev(starting_host, dev_addr, dev_mac, dev_param, os_type)
        if dev_results[2]:
            ports.append(dev_results[2])
            dev_match = cdp_matcher(dev_results[0], dev_results[1], dev_results[2], dev_results[3])
            if dev_match[1] == False:  # Check whether to stop search
                if 'NX-OS' in dev_match[2]:     # Setting device type for next hop to access
                    os_type = 'cisco_nxos'
                else:
                    os_type = 'cisco_ios'
                if dev_match[0] in hops:  # Guard against loop
                    print('** Loop detected! stopping search.. ')
                    break
                hops.append(dev_match[0])
                starting_host = dev_match[0]

            else:  # If end search is True
                if dev_match[0] != 'N/A':  # If last found was a CDP device and not a L2 switch
                    hops.append(dev_match[0])
                if dev_match[0] == dev_addr:  # Remove destintaion address from list
                    hops.pop()
                break
        else:
            break

        
    return hops, ports


def present_path(addrs,ports):
    #displays a chain of address/port pairs for each device in path
    path = list(zip(addrs,ports))
    for pair in path:
        if pair == path[-1]:
            print (pair)
        else:
            print (str(pair) + ' --> ', end='')

# ----------------------------------------------------------------------------

if __name__ == '__main__':

    args = get_args()

    print()
    print('#' * 49)
    print('#' + ((' ') * 7) + '-- Running Cisco Device Finder --' + ((' ') * 7) + '#')
    print('#' * 49)
    print()

    if args.stg_address:
        starting_host = args.stg_address
    else:
        starting_host = input('Enter starting host IP: ')

    if args.dst_address:
        dev_addr = args.dst_address
    else:
        dev_addr = input('Enter search IP address: ')

    if args.mac_address:
        mac_addr = args.mac_address
    else:
        mac_addr = input('Enter search MAC address (****.****.****): ')
    
        
    user = input('username: ')
    pw = getpass.getpass()
    
    start_time = datetime.now()
    
    os_type = pyip.inputMenu(['ios', 'nxos'],prompt='Enter Starting Host OS type\n' ,numbered=True)
    

    if os_type == 'nxos':
        os_type = 'cisco_nxos'
    else:
        os_type = 'cisco_ios'


    dev_param = {'device_type': os_type,
                 'host': '',
                 'username': user,
                 'password': pw,                 
                 'timeout': 15,
                 'global_delay_factor': 0.5,  
                 }

    all_addrs, all_ports = finder(starting_host, dev_addr, mac_addr, dev_param, os_type)
    
    # Present path consolidated results to user
    print(f'** Trace path for mac address: {mac_addr.upper()} ')
    present_path(all_addrs, all_ports)
    end_time = datetime.now()
    print("** Transaction time: {} \n".format(end_time - start_time))

