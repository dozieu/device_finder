#!/usr/bin/env python3
# source venv/bin/activate

import os
import getpass
from datetime import datetime
from netmiko import ConnectHandler, file_transfer
from ntc_templates.parse import parse_output
import re


os.environ["NET_TEXTFSM"] = "./ntc-templates/templates/"


def output_sieve(ios_response):
    ''' Accepts lines and returns list of each line's result of the split method performed on it'''
    try:
        output_l = []
        for i in ios_response.splitlines():
            j = i.split()
            output_l.append(j)

    except Exception as exc:
        print('There was a problem: %s' % (exc))
    return output_l


def port_str_splitter(portstring):
    '''used to seperate port type and port number from portstring '''
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
            # -- signals that it has found Portchannel and displays port members
            print(output + '\n')
            print(f'Checking CDP for port: {port_info}\n')
            output = ''
            output = net_connect.send_command('show cdp neighbors detail', strip_prompt=True,
                                              strip_command=True, use_textfsm=True)
            net_connect.disconnect()
    except Exception as exc:
        print('There was a problem: error with device information')
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
    for i in output:
        # Searches through result of show cdp neigbors detail to find IP,OS, and Capabilities
        local_port_num = (i['local_port']).split('net')
        if port_type == i['local_port'][:2] and local_port_num[1] == port_num:  # Match interface

            found_port = i['local_port']
            if ('management_ip') in i:  # Set found_ip
                found_ip = i['management_ip']
            if ('mgmt_ip') in i:
                found_ip = i['mgmt_ip']
            if ('software_version') in i:   # Set found_os
                found_os = i['software_version']
            if ('version') in i:
                found_os = i['version']

            if i['capabilities'] == 'Host':  # -- In case you encounter other devices e.g. Cisco WLC
                print(
                    f'** Non-switch detected - Unable to trace beyond {host_ip}')
                end_search = True

            if dst_ip == found_ip:  # Stop if IP matches destination IP
                print(
                    f'** Device is CDP enabled and found on {host_ip} {found_port}')
                end_search = True
            break
    else:
        print(f'** No CDP info. Last hop is -> {host_ip} port {port_info}')
        end_search = True

    found_neighbor = [found_ip, end_search, found_os]
    return found_neighbor


def finder(starting_host, dev_addr, dev_mac, dev_param, os_type):
    ''' finder uses the results from check_dev to know if to jump to next device.
    It checks whether to end search or if to update "os_type" and "starting_host" for next call to check_dev.
    Function returns a list of hops showing the layer 2 path'''

    start_time = datetime.now()
    print(f'\nStarting from {starting_host}\n')
    hops = [starting_host]

    while True:
        if starting_host == 'N/A':
            break
        j = check_dev(starting_host, dev_addr, dev_mac, dev_param, os_type)
        if j[2]:
            k = cdp_matcher(j[0], j[1], j[2], j[3])
            if k[1] == False:  # Check whether to stop search
                if 'NX-OS' in k[2]:     # Setting device type for next hop to access
                    os_type = 'cisco_nxos'
                else:
                    os_type = 'cisco_ios'
                if k[0] in hops:  # guard against loop
                    print('** Loop detected! stopping search.. ')
                    break
                hops.append(k[0])
                starting_host = k[0]

            else:  # If end search is True
                if k[0] != 'N/A':  # If last found was a CDP device and not a L2 switch
                    hops.append(k[0])
                if k[0] == dev_addr:  # Remove destintaion address from list
                    hops.pop()
                break
        else:
            break

    print(f'** Trace path for mac {dev_mac} ' + '->' + str(hops))
    end_time = datetime.now()
    print("** Transaction time: {} \n".format(end_time - start_time))

    return hops


# ----------------------------------------------------------------------------

if __name__ == '__main__':

    print()
    print('#' * 49)
    print('#' + ((' ') * 7) + '-- Running Cisco Device Finder --' + ((' ') * 7) + '#')
    print('#' * 49)
    print()
    
    user = input('username: ')
    pw = getpass.getpass()
    starting_host = input('Enter starting host IP: ')
    dev_addr = input('Enter search IP address: ')
    device_mac = input('Enter search MAC address (****.****.****): ')
    os_type = input('Enter Starting Host OS type ("ios" or "nxos"): ')


    if os_type == 'nxos':
        os_type = 'cisco_nxos'
    else:
        os_type = 'cisco_ios'


    dev_param = {'device_type': os_type,
                 'host': '',
                 'username': user,
                 'password': pw,                 
                 'timeout': 15,
                 'global_delay_factor': 0.2,  
                 }

    op = finder(starting_host, dev_addr, device_mac, dev_param, os_type)

