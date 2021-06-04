# flake8: noqa: C901
import dataclasses
import functools
import json
import struct
import sys
import threading
from _ctypes import Structure
from copy import deepcopy
from ctypes import c_byte, c_uint16, c_uint32
from datetime import datetime

import click

from ios_device.cli.base import InstrumentsBase
from ios_device.cli.cli import Command, print_json
from ios_device.servers.DTXSever import InstrumentRPCParseError
from ios_device.util import Log
from ios_device.util.dtxlib import get_auxiliary_text
from ios_device.util.kc_data import kc_data_parse
from ios_device.util.variables import LOG

log = Log.getLogger(LOG.Instrument.value)


@click.group()
def cli():
    """ instruments cli """


@cli.group(short_help='run instruments service')
def instruments():
    """
    运行 instruments 组件相关服务

    run instruments service
    """


@instruments.command('runningProcesses', cls=Command, short_help='Show running process list')
def cmd_running_processes(udid, network, format):
    """
    显示正在运行的进程信息

    Show running process list
     """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        processes = rpc.device_info.runningProcesses()
        print_json(processes, format)


@instruments.command('applist', cls=Command)
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter')
def cmd_application(udid, network, format, bundle_id):
    """ Show application list """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        apps = rpc.application_listing(bundle_id)
        print_json(apps, format)


@instruments.command('kill', cls=Command)
@click.option('-p', '--pid', type=click.INT, default=None, help='Process ID to filter')
@click.option('-n', '--name', default=None, help='Process app name to filter')
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter')
def cmd_kill(udid, network, format, pid, name, bundle_id):
    """ Kill a process by its pid. """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        if bundle_id or name:
            pid = rpc.get_pid(bundle_id, name)
        if not pid:
            log.error(f'The pid: {pid} did not start. Try "-h or --help" for help')
            return
        rpc.kill_app(pid)
        print(f'Kill {pid} ...')


@instruments.command('launch', cls=Command)
@click.option('--bundle_id', default=None, help='Process app bundleId to filter')
@click.option('--app_env', default=None, help='App launch environment variable')
def cmd_launch(udid, network, format, bundle_id: str, app_env: dict):
    """
    Launch a process.
    :param bundle_id: Arguments of process to launch, the first argument is the bundle id.
    :param app_env: App launch environment variable
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        pid = rpc.launch_app(bundle_id=bundle_id, app_env=app_env)
        print(f'Process launched with pid {pid}')


@instruments.group('information')
def information():
    """ System information. """


@information.command('system', cls=Command)
def cmd_information_system(udid, network, format):
    """ Print system information. """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        print_json(rpc.device_info.systemInformation(), format)


@information.command('hardware', cls=Command)
def cmd_information_hardware(udid, network, format):
    """ Print hardware information. """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        print_json(rpc.device_info.hardwareInformation(), format)


@information.command('network', cls=Command)
def cmd_information_network(udid, network, format):
    """ Print network information. """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        print_json(rpc.device_info.networkInformation(), format)


@instruments.command('xcode_energy', cls=Command)
@click.option('-p', '--pid', type=click.INT, default=None, help='Process ID to filter')
@click.option('-n', '--name', default=None, help='Process app name to filter')
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter')
def cmd_xcode_energy(udid, network, pid, name, bundle_id, format):
    """ Print process about current network activity.  """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        if bundle_id or name:
            pid = rpc.get_pid(bundle_id, name)
        if not pid:
            log.error(f'The pid: {pid} did not start. Try "--help" for help')
            return
        rpc.xcode_energy(pid)


@instruments.command('network_process', cls=Command)
@click.option('-p', '--pid', type=click.INT, default=None, help='Process ID to filter')
@click.option('-n', '--name', default=None, help='Process app name to filter')
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter')
def cmd_network_process(udid, network, pid, name, bundle_id, format):
    """ Print process about current network activity.  """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        if bundle_id or name:
            pid = rpc.get_pid(bundle_id, name)
        if not pid:
            log.error(f'The pid: {pid} did not start. Try "--help" for help')
            return
        rpc.xcode_network(pid)


@instruments.command('networking', cls=Command)
def cmd_networking(udid, network, format):
    """ Print information about current network activity. """
    headers = {
        0: ['InterfaceIndex', "Name"],
        1: ['LocalAddress', 'RemoteAddress', 'InterfaceIndex', 'Pid', 'RecvBufferSize', 'RecvBufferUsed',
            'SerialNumber', 'Kind'],
        2: ['RxPackets', 'RxBytes', 'TxPackets', 'TxBytes', 'RxDups', 'RxOOO', 'TxRetx', 'MinRTT', 'AvgRTT',
            'ConnectionSerial']
    }
    msg_type = {
        0: "interface-detection",
        1: "connection-detected",
        2: "connection-update",
    }

    def on_callback_message(res):
        from socket import inet_ntoa, htons, inet_ntop, AF_INET6
        class SockAddr4(Structure):
            _fields_ = [
                ('len', c_byte),
                ('family', c_byte),
                ('port', c_uint16),
                ('addr', c_byte * 4),
                ('zero', c_byte * 8)
            ]

            def __str__(self):
                return f"{inet_ntoa(self.addr)}:{htons(self.port)}"

        class SockAddr6(Structure):
            _fields_ = [
                ('len', c_byte),
                ('family', c_byte),
                ('port', c_uint16),
                ('flowinfo', c_uint32),
                ('addr', c_byte * 16),
                ('scopeid', c_uint32)
            ]

            def __str__(self):
                return f"[{inet_ntop(AF_INET6, self.addr)}]:{htons(self.port)}"

        data = res.parsed
        if data[0] == 1:
            if len(data[1][0]) == 16:
                data[1][0] = str(SockAddr4.from_buffer_copy(data[1][0]))
                data[1][1] = str(SockAddr4.from_buffer_copy(data[1][1]))
            elif len(data[1][0]) == 28:
                data[1][0] = str(SockAddr6.from_buffer_copy(data[1][0]))
                data[1][1] = str(SockAddr6.from_buffer_copy(data[1][1]))
        print_json((msg_type[data[0]] + json.dumps(dict(zip(headers[data[0]], data[1])))))

    with InstrumentsBase(udid=udid, network=network) as rpc:
        rpc.networking(on_callback_message)


@instruments.command('sysmontap', cls=Command)
@click.option('-t', '--time', type=click.INT, default=1000, help='Output interval time (ms)')
@click.option('-p', '--pid', type=click.INT, default=None, help='Process ID to filter')
@click.option('-n', '--name', default=None, help='Process app name to filter')
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter.Omit show all')
@click.option('--processes', is_flag=True, help='Only output process information')
@click.option('--sort', help='Process field sorting')
@click.option('--proc_filter', help='Process param to filter split by ",". Omit show all')
@click.option('--sys_filter', help='System param to filter split by ",". Omit show all')
def cmd_sysmontap(udid, network, format, time, pid, name, bundle_id, processes, sort, proc_filter,
                  sys_filter):
    """ Get performance data """

    def on_callback_message(res):
        if isinstance(res.parsed, list):
            data = deepcopy(res.parsed)
            processes_data = {}
            for index, row in enumerate(res.parsed):
                if 'Processes' in row:
                    data[index]['Processes'] = {}
                    for _pid, process in row['Processes'].items():
                        process_attributes = dataclasses.make_dataclass('SystemProcessAttributes',
                                                                        proc_filter or rpc.process_attributes)
                        attrs = process_attributes(*process)
                        if pid and pid != _pid:
                            continue
                        if name and attrs.name != name:
                            continue
                        if processes:
                            processes_data[f'{attrs.name}'] = attrs.__dict__
                            continue
                        data[index]['Processes'][f'{attrs.name}'] = attrs.__dict__
                    data[index]['Processes'] = sorted(data[index]['Processes'].items(),
                                                      key=lambda d: d[1].get(sort, 0),
                                                      reverse=True)

                if 'System' in row:
                    if 'SystemAttributes' in data[index]:
                        del data[index]['SystemAttributes']
                    if 'ProcessesAttributes' in data[index]:
                        del data[index]['ProcessesAttributes']
                    data[index]['System'] = dict(zip(rpc.system_attributes, row['System']))
            if processes:
                processes_data = sorted(processes_data.items(), key=lambda d: d[1].get(sort, 0) or 0,
                                        reverse=True)
                print_json(processes_data, format)
            else:
                print_json(print_json, format)

    with InstrumentsBase(udid=udid, network=network) as rpc:

        if proc_filter:
            data = rpc.device_info.sysmonProcessAttributes()
            proc_filter = proc_filter.split(',')
            proc_filter.extend(['name', 'pid'])
            proc_filter = list(set(proc_filter))
            for proc in proc_filter:
                if proc not in data:
                    log.warn(f'{proc_filter} value：{proc} not in {data}')
                    return
            rpc.process_attributes = proc_filter

        if sys_filter:
            data = rpc.device_info.sysmonSystemAttributes()
            sys_filter = sys_filter.split(',')
            for sys in sys_filter:
                if sys not in data:
                    log.warn(f'{sys_filter} value：{sys} not in {data}')
                    return
            rpc.system_attributes = sys_filter

        if bundle_id:
            app = rpc.application_listing(bundle_id)
            name = app.get('ExecutableName')
        rpc.sysmontap(on_callback_message, time)


@instruments.group()
def condition():
    """
    Set system running condition
    """


@condition.command('get', cls=Command)
def cmd_get_condition_inducer(udid, network, format):
    """ get aLL condition inducer configuration
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        ret = rpc.get_condition_inducer()
        print_json(ret)


@condition.command('set', cls=Command)
@click.option('-c', '--condition_id', default=None, help='Process app bundleId to filter')
@click.option('-p', '--profile_id', default='', help='start wda port')
def cmd_set_condition_inducer(udid, network, format, condition_id, profile_id):
    """ set condition inducer
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        ret = rpc.set_condition_inducer(condition_id, profile_id)
        print_json(ret, format)


@instruments.command('xcuitest', cls=Command)
@click.option('-b', '--bundle_id', default=None, help='Process app bundleId to filter')
@click.option('-p', '--port', default='', help='start wda port')
def cmd_xcuitest(udid, network, format, bundle_id, port):
    """ Run XCTest required WDA installed.
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        rpc.xctest(bundle_id, port)


@instruments.command('fps', cls=Command)
@click.option('-t', '--time', type=click.INT, default=1000, help='Output interval time (ms)')
def cmd_graphics(udid, network, format, time):
    """ Get graphics fps
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        def on_callback_message(res):
            data = res.parsed
            print_json({"currentTime": str(datetime.now()), "fps": data['CoreAnimationFramesPerSecond']}, format)

        rpc.graphics(on_callback_message, time)


@instruments.command('notifications', cls=Command)
def cmd_notifications(udid, network, format):
    """Get mobile notifications
    """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        def on_callback_message(res):
            print_json(get_auxiliary_text(res.raw), format)

        rpc.mobile_notifications(on_callback_message)


@instruments.command('stackshot', cls=Command)
@click.option('--out', type=click.File('w'), default=None)
def stackshot(udid, network, format, out):
    """ Dump stackshot information. """
    with InstrumentsBase(udid=udid, network=network) as rpc:
        stopSignal = threading.Event()

        def on_callback_message(res):
            if type(res.plist) is InstrumentRPCParseError:
                buf = res.raw.get_selector()
                if buf.startswith(b'\x07X\xa2Y'):
                    stopSignal.set()
                    kc_data = kc_data_parse(buf)
                    if out is not None:
                        json.dump(kc_data, out, indent=4)
                        log.info(f'Successfully dump stackshot to {out.name}')
                    else:
                        print_json(kc_data, format)
        rpc.core_profile_session(on_callback_message, stopSignal)

# @instruments.command('power', cls=Command)
# def cmd_power(udid, network, format):
#     """Get mobile power
#     """
#     headers = ['startingTime', 'duration', 'level']  # DTPower
#     ctx = {
#         'remained': b''
#     }
#     def on_callback_message(res):
#         print(res.parsed)
#         ctx['remained'] += res.parsed['data']
#         cur = 0
#         while cur + 3 * 8 <= len(ctx['remained']):
#             print("[level.dat]", dict(zip(headers, struct.unpack('>ddd', ctx['remained'][cur: cur + 3 * 8]))))
#             cur += 3 * 8
#             pass
#         ctx['remained'] = ctx['remained'][cur:]
#
#     with InstrumentsBase(udid=udid, network=network) as rpc:
#
#         rpc.power(on_callback_message)