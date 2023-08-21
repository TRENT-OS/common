#!/usr/bin/python3

import sys
import threading
import traceback
import socket
import selectors
import os
from enum import IntEnum
import socket
import time

from . import tools
from .tools import Timeout_Checker
from . import process_tools
from . import board_automation



#===============================================================================
#===============================================================================

class TcpBridge():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer

        self.socket_client = None

        self.server_socket = None
        self.server_socket_client = None

        # the buffer size value has has been picked based on observations, the
        # largest value seen so far was 4095, which might be related to
        # - the 4 KiByte pages that ARM and RISC-V uses
        # - seL4/CAmkES based systems often use shared buffers of 4 KiByte.
        self.buffer_size = 8192

        self.sel = selectors.DefaultSelector()

        #-----------------------------------------------------------------------
        def socket_event_thread(thread):

            # this is a daemon thread that will be killed automatically when
            # the main thread dies. Thus there is no abort mechanism here
            while True:

                for key, mask in self.sel.select():

                    #self.print(f'callback {key} {mask}')
                    callback = key.data

                    try:
                        callback(key.fileobj, mask)
                    except Exception as e:
                        (e_type, e_value, e_tb) = sys.exc_info()
                        self.print(f'EXCEPTION in socket callback: {e}\n'
                                   ''.join(traceback.format_exception_only(e_type, e_value)) +
                                   '\nCall stack:\n' +
                                   ''.join(traceback.format_tb(e_tb)))

        tools.run_in_thread(socket_event_thread)


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(f'{__class__.__name__}: {msg}')


    #---------------------------------------------------------------------------
    def stop_server(self):

        socket_srv = self.server_socket
        if socket_srv is None:
            # there is no server running
            return

        self.server_socket = None
        self.sel.unregister(socket_srv)

        socket_src_cli = self.server_socket_client
        if socket_src_cli is not None:
            self.server_socket_client = None
            socket_src_cli.close()

        socket_srv.close()


    #---------------------------------------------------------------------------
    def shutdown(self):

        self.stop_server()

        s = self.socket_client
        if s is not None:
            self.socket_client = None
            s.close()


    #-----------------------------------------------------------------------
    # this callback is invoked when there is data to be read from the
    # server
    def callback_socket_read(
            self,
            sock,
            mask,
            cb_exp_src,
            cb_exp_dst,
            cb_closed):


        socket_src = cb_exp_src()
        if not socket_src:
            return

        if (sock != socket_src):
            return

        # read data from the socket. Since we are in a callback for a read
        # event, this is not supposed to block even if we use blocking sockets.
        # If we read no data, this means the socket has been closed. Note that
        # a non-blocking socket behaves in the same way, it throws an exception
        # if there is no data to read.
        data = None
        try:
            data = sock.recv(self.buffer_size)
        except ConnectionResetError:
            # socket already closed
            data = None

        if not data:
            cb_closed(sock)
            return

        socket_dst = cb_exp_dst()
        if not socket_dst:
            return

        socket_dst.sendall(data)


    #---------------------------------------------------------------------------
    # connect the bridge to a server, use infinite timeout by default
    def connect_to_server(self, addr, port, timeout_sec = None):

        timeout = Timeout_Checker(timeout_sec)

        peer = (addr, port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # try to connect to server
        while True:
            try:
                s.connect(peer)
                break

            except Exception as e:
                if not timeout or timeout.has_expired():
                    self.print(f'EXCEPTION connecting socket: {e}')
                    raise Exception(f'could not connect to {addr}:{port}')

            # using 250 ms here seems a good trade-off. Even if there is some
            # system load, we usually succeed after one retry. Using 100 ms
            # here just end up on more retries as it seems startup is either
            # quite quick or it takes some time.
            timeout.sleep(0.25)

        self.print(f'TCP connection established to {addr}:{port}')
        self.socket_client = s

        #-----------------------------------------------------------------------
        def cb_closed(sock):
            self.sel.unregister(sock)
            self.socket_client = None


        #-----------------------------------------------------------------------
        def cb_read(sock, mask):
            self.callback_socket_read(
                sock,
                mask,
                lambda: self.socket_client,
                lambda: self.server_socket_client,
                cb_closed)

        self.sel.register(s, selectors.EVENT_READ, cb_read)


    #---------------------------------------------------------------------------
    def start_server(self, port):

        #-----------------------------------------------------------------------
        def cb_closed(sock):
            self.sel.unregister(sock)
            self.server_socket_client = None


        #-----------------------------------------------------------------------
        def cb_read(sock, mask):
            self.callback_socket_read(
                sock,
                mask,
                lambda: self.server_socket_client,
                lambda: self.socket_client,
                cb_closed)


        #-----------------------------------------------------------------------
        def cb_accept(sock, mask):
            if self.server_socket != sock:
                return

            (s, addr) = sock.accept()
            self.print(f'connection from {addr}')
            self.server_socket_client = s
            self.sel.register(s, selectors.EVENT_READ, cb_read)


        if self.socket_client is None:
            raise Exception('not connected to any server')

        peer = ('127.0.0.1', port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # if we execute the test script in the container in quick succession
        # the second execution would fail due to an unavailable port.
        # Setting it as reusable, allows us to avoid this failure case.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(peer)
        except:
            s.close()
            raise Exception(f'could not create server socket on port {port}')

        self.server_socket = s
        s.listen(0)

        self.sel.register(s, selectors.EVENT_READ, cb_accept)


    #---------------------------------------------------------------------------
    # get the QEMU serial port socket, if the TCP bridge is running this
    # implies shutting it down
    def get_source_socket(self):

        self.stop_server()

        sock = self.socket_client
        if sock is None:
            return None

        # unregistering throws a KeyError exception if the socket is not
        # registered. This can happen, because get_source_socket() may be
        # called multiple times during a test run.
        try:
            self.sel.unregister(sock)
        except KeyError:
            # if source_socket() has been called before, the socket was already
            # unregistered then. So we can ignore this exception.
            pass

        return sock


#===============================================================================
#===============================================================================

class QEMU_AppWrapper:

    #---------------------------------------------------------------------------
    def __init__(self, params_dict = dict()):

        self.config = {
            'qemu-bin': None,
            'machine': None,
            'dtb': None,
            'cpu': None,
            'cores': None,
            'memory': None,
            # currently we don't have any platform that has a monitor
            'graphic': None,
            # 'kernel' is the common option to boot an OS like Linux,
            # 'bios' is machine specific to load firmware. On RISC-V,
            # 'bios' allows booting the system in M-Mode and install a
            # custom SBI, while 'kernel' will make QEMU use an OpenSBI
            # firmware that comes with QEMU and boots the given OS in
            # S-Mode.
            'bios': None,
            'kernel':  None,
            # enable for instruction tracing
            'singlestep': False,
            # There can be multiple drives, devices, SD-Card or NICs.
            # Python guarantees the order is preserved when adding
            # elements to an array.
            'drives': [],
            'devices': [],
            'serial_ports': [],
            'raw_params': [],
            # non-QEMU related settings, e.g. for OS
            'syslog-uart': 0,
            # Defaults are set, add or overwrite custom config. Python support
            # for merging dictionaries:
            #   Python >= 3.9:  z = x | y
            #   Python >= 3.5:  z = {**x, **y}
            #   else:           z = x.copy(); z.update(y); return z
            **params_dict
        }

        # SD card devices based on images need unique numbers.
        self.num_sdcard_images = 0

    #---------------------------------------------------------------------------
    def setup(self, run_context):
        pass # nothing special here


    #---------------------------------------------------------------------------
    def add_params(self, *argv):
        raw_params = self.config['raw_params']
        for arg in argv:
            if isinstance(arg, list):
                raw_params.extend(arg)
            else:
                raw_params.append(arg)


    #---------------------------------------------------------------------------
    def serialize_param_dict(self, arg_dict):
        # Python 3.6 made the standard dict type maintain the insertion
        # order. With older versions the iteration order is random.
        return None if arg_dict is None \
               else ','.join([
                    (f'{key}' if value is None \
                        else f'{key}={value}')
                    for (key, value) in arg_dict.items()
               ])


    #---------------------------------------------------------------------------
    def add_serial_port(self, port):
        # A list preserves the order of added elements
        self.config['serial_ports'] += [port]


    #---------------------------------------------------------------------------
    def add_drive(self, param_dict):
        # A list preserves the order of added elements
        self.config['drives'] += [param_dict]


    #---------------------------------------------------------------------------
    def add_device(self, dev_type, sub_type, param_dict = None):
        # A list preserves the order of added elements
        self.config['devices'] += [ (dev_type, sub_type, param_dict) ]


    #---------------------------------------------------------------------------
    def add_nic(self, nic_type, param_dict = None):
        # We enforce an explicit NIC type. QEMU's default is 'user' if nothing
        # is given, but callers should not rely on that. A 'user' NIC puts the
        # emulated machine in network behind a NAT and shared the host's network
        # connection. So TCP/UDP will works, but ICMP (ping) will not.
        if nic_type is None:
            raise Exception('No NIC type given')
        # a NIC is just another device.
        self.add_device('nic', nic_type, param_dict)


    #---------------------------------------------------------------------------
    def add_nic_tap(self, tap, param_dict = None):
        full_param_dict = {
            'ifname': tap,
            'script': 'no'
        }
        if param_dict:
            full_param_dict.update(param_dict)
        self.add_nic('tap', full_param_dict)


    #---------------------------------------------------------------------------
    def add_dev_char_socket(self, param_dict):
        assert len(param_dict) > 0  # there must be parameters
        # Any chardevice based on a socket is basically just another
        # device
        self.add_device('chardev', 'socket', param_dict)


    #---------------------------------------------------------------------------
    def add_sdcard_from_image(self, sd_card_image):
        dev_id = f'sdcardimg{self.num_sdcard_images}'
        self.num_sdcard_images += 1
        # Add a drive with the file and connect the SD-Card to it.
        self.add_drive({
            'id': dev_id,
            'file': sd_card_image,
            'format': 'raw',
        })
        self.add_device('device', 'sd-card', {'drive': dev_id})


    #---------------------------------------------------------------------------
    def add_dev_loader(self, param_dict):
        assert len(param_dict) > 0  # there must be loader parameters
        self.add_device('device', 'loader', param_dict)


    #---------------------------------------------------------------------------
    def init_memory_at(self, address, value, param_dict = dict()):
        full_param_dict = {
            'addr': address,
            'data': value,
            'data-len': 4
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def load_blob(self, address, filename, param_dict = dict()):

        if not os.path.isfile(filename):
            raise Exception(f'Missing blob file: {filename}')

        full_param_dict = {
            'addr': address,
            'file': filename
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def load_elf(self, filename, param_dict = dict()):

        if not os.path.isfile(filename):
            raise Exception(f'Missing ELF file: {filename}')

        full_param_dict = {
            'file': filename
        }
        full_param_dict.update(param_dict)
        self.add_dev_loader(full_param_dict)


    #---------------------------------------------------------------------------
    def sys_log_setup(self, sys_log_path, host, port, id):
        # In addition to outputting the guest system log to a log file,
        # we are opening a 2-way TCP socket connected to the same serial
        # device that allows the test suite to communicate with the
        # guest during the test execution.
        dev_id = f'chardev{id}'
        self.add_dev_char_socket({
            'id': dev_id,
            'host': host,
            'port': port,
            'server': 'on',
            'wait': 'off',
            'logfile': sys_log_path,
            'signal': 'off'
        })
        self.add_serial_port(f'chardev:{dev_id}')


    #---------------------------------------------------------------------------
    def get_machine(self):
        param = self.config.get('machine', None)
        if param and isinstance(param, list):
            assert isinstance(param[0], str)
            assert isinstance(param[1], dict) # may have 'dumpdtb=<filename>'
            param = param[0]
        return param


    #---------------------------------------------------------------------------
    def start(
        self,
        log_file_stdout,
        log_file_stderr,
        additional_params = None,
        printer = None,
        print_log = False):

        def check_param(cfg, name, alias=None, transform_fn=None):
            param = cfg.pop(name, None)
            return [] if not param else [
                f'-{alias if alias else name}',
                transform_fn(param) if transform_fn else param
            ]

        # Create a shallow copy of the configuration, so we can remove items
        # that are turned into QEMU parameters. Any remaining item is unused
        # configuration data, we remove the known elements and expect that the
        # config is empty. If there are items left, raise an error, because
        # these seem unsupported config parameters.
        cfg = self.config.copy()

        # build the command line
        cmd_arr = []

        param = cfg.pop('qemu-bin', None)
        if param is None:
            raise Exception(f'no QEMU binary set')
        cmd_arr += [ param ]

        param = cfg.pop('machine', None)
        if param is None:
            raise Exception('no QEMU machine set')
        if isinstance(param, list):
            assert isinstance(param[0], str)
            assert isinstance(param[1], dict) # may have 'dumpdtb=<filename>'
            param = param[0] + ',' + self.serialize_param_dict(param[1])
        cmd_arr += ['-machine', param]

        # passing a DTB with the hardware details is a nice feature, but it's
        # supported by the Xilinx-QEMU fork only.
        cmd_arr += check_param(cfg, 'dtb');

        cmd_arr += check_param(cfg, 'cpu');
        cmd_arr += check_param(cfg, 'cores', 'smp', lambda p: str(p));
        cmd_arr += check_param(cfg, 'memory', 'm', lambda p: f'size={p}M');

        param = cfg.pop('graphic', False)
        if not param: # works also if set to None
            cmd_arr += ['-nographic']

        cmd_arr += check_param(cfg, 'singlestep');
        cmd_arr += check_param(cfg, 'kernel');
        cmd_arr += check_param(cfg, 'bios');

        # SD-Card images are basically a device/drive combination
        param = cfg.pop('sdcard_images', [])
        for i, img in enumerate(param):
            dev_id = f'sdcardimg{i}'
            self.add_drive({
                'id': dev_id,
                'file': sd_card_image,
                'format': 'raw',
            })
            self.add_dev_sdcard({'drive': dev_id})

        param = cfg.pop('drives', [])
        for param_dict in param:
            assert len(param_dict) > 0  # there must be parameters
            cmd_arr += ['-drive', self.serialize_param_dict(param_dict)]

        param = cfg.pop('devices', [])
        for (dev_type, sub_type, param_dict) in param:
            cmd_arr += [
                f'-{dev_type}',
                sub_type if param_dict is None \
                else ','.join([
                    sub_type,
                    self.serialize_param_dict(param_dict)
                ])
            ]

        # connect all serial ports
        param = cfg.pop('serial_ports', [])
        for p in param:
            cmd_arr += ['-serial', p if p else 'null']

        # add raw parameters
        cmd_arr += cfg.pop('raw_params', [])

        # ToDo: Check if we still have to support this hack to pass additional
        #       parameters to QEMU to load some data into its memory. There
        #       should be a better way.
        if additional_params:
            for param in additional_params:
                if param[2] == Additional_Param_Type.VALUE:
                    self.init_memory_at(param[0], param[1])
                elif param[2] == Additional_Param_Type.BINARY_IMG:
                    self.load_blob(param[0], param[1])
                else:
                    raise Exception(f'QEMU: additional parameter type "{param[2]}" not supported')

        # non-QEMU specific settings
        param = cfg.pop('syslog-uart')
        assert param in [0, 1]

        # now all parameters must have been processed
        if cfg:
            raise Exception(f'unsupported QEMU config items: {cfg}')

        if printer:
            printer.print(f'QEMU: {" ".join(cmd_arr)}')

        process = process_tools.ProcessWrapper(
                    cmd_arr,
                    log_file_stdout = log_file_stdout,
                    log_file_stderr = log_file_stderr,
                    printer = printer,
                    name = 'QEMU' )
        assert process is not None # should have created an exception

        process.start(print_log)

        return process


#-------------------------------------------------------------------------------
class QEMU_xilinx(QEMU_AppWrapper):

    #---------------------------------------------------------------------------
    def __init__(self, param_dict = dict()):

        super().__init__(
            {
                'qemu-bin': '/host/build-xilinx-qemu/qemu-system-aarch64',
                'machine':  'arm-generic-fdt',
                # Defaults are set, add or overwrite custom config.
                **param_dict
            })

        self.qemu_pmu = QEMU_AppWrapper({
            'qemu-bin': '/host/build-xilinx-qemu/qemu-system-microblazeel',
            'machine':  'microblaze-fdt',
        })


    #---------------------------------------------------------------------------
    def setup(self, run_context):

        # ToDo: This is still a bit zcu102 specific, but that is the only
        #       platform we use at the moment.

        res_dir = os.path.join(run_context.resource_dir, 'zcu102_sd_card')
        if not os.path.isdir(res_dir):
            raise Exception(f'res_dir Directory {res_dir} does not exist!')

        log_dir = run_context.log_dir
        if not os.path.isdir(log_dir):
            raise Exception(f'log_dir Directory {log_dir} does not exist!')

        # PE (ARM cluster) software
        pe_dtb          = os.path.join(res_dir, 'zcu102-arm.dtb')
        pe_bl_elf       = os.path.join(res_dir, 'bl31.elf')
        pe_u_boot_elf   = os.path.join(res_dir, 'u-boot.elf')
        # PMU (MicroBlaze) software
        pmu_dtb        = os.path.join(res_dir, 'zynqmp-pmu.dtb')
        pmu_kernel_elf = os.path.join(res_dir, 'pmu_rom_qemu_sha3.elf')
        pmu_fw_elf     = os.path.join(res_dir, 'pmufw.elf')

        if not os.path.isfile(pe_dtb) or \
           not os.path.isfile(pe_bl_elf) or \
           not os.path.isfile(pe_u_boot_elf) or \
           not os.path.isfile(pmu_dtb) or \
           not os.path.isfile(pmu_kernel_elf) or \
           not os.path.isfile(pmu_fw_elf):
            raise Exception('The resource directory does not contain \
                             all necessary files to start QEMU')

        self.config['dtb'] = pe_dtb
        self.add_params(
            '-global', 'xlnx,zynqmp-boot.cpu-num=0',
            '-global', 'xlnx,zynqmp-boot.use-pmufw=true',
            '-machine-path', log_dir)
        self.load_elf(pe_bl_elf, {'cpu-num': 0})
        self.load_elf(pe_u_boot_elf)

        self.qemu_pmu.config['dtb'] = pmu_dtb
        self.qemu_pmu.config['kernel'] = pmu_kernel_elf
        self.qemu_pmu.add_params('-machine-path', log_dir)
        self.qemu_pmu.load_elf(pmu_fw_elf)


    #---------------------------------------------------------------------------
    def start(
        self,
        log_file_stdout,
        log_file_stderr,
        additional_params = None,
        printer = None,
        print_log = False):

        def pmu_logfile(parent_log_file, channel):
            return os.path.join(
                    os.path.dirname(parent_log_file),
                    f'qemu_pmu_{channel}.txt')

        # start PMU (MicroBlaze) instance first
        process_qemu_pmu = self.qemu_pmu.start(
            log_file_stdout = pmu_logfile(log_file_stdout, 'out'),
            log_file_stderr = pmu_logfile(log_file_stderr, 'err'),
            additional_params = None,
            printer = printer,
            print_log = print_log
        )

        # start PE (ARM Cluster) instance afterwards
        process_qemu_pe = super().start(
            log_file_stdout = log_file_stdout,
            log_file_stderr = log_file_stderr,
            additional_params = additional_params,
            printer = printer,
            print_log = print_log
        )

        class Process_qemu_zynqmp_microblaze():
            def __init__(self, processes):
                self.processes = processes
            def is_running(self):
                return all([p.is_running() for p in self.processes])
            def terminate(self):
                for p in self.processes: p.terminate()

        return Process_qemu_zynqmp_microblaze([process_qemu_pe, process_qemu_pmu])


#-------------------------------------------------------------------------------
def get_qemu(target, printer=None):

    qemu_cfgs = {
        'sabre': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  'sabrelite',
            'memory':   1024,
            'syslog-uart': 1, # kernel log is on UART1, not UART0
        },
        'migv_qemu': {
            'qemu-bin': '/opt/hc/migv/bin/qemu-system-riscv64',
            'machine': 'mig-v',
            'memory':   1024,
        },
        'hifive': {
            'qemu-bin': 'qemu-system-riscv64',
            'machine':  'sifive_u',
            'memory':   8192,
            # Core setting works as:
            #   1: 1x U54, 1x E51
            #   2: 1x U54, 1x E51
            #   3  2x U54, 1x E51
            #   4: 3x U54, 1x E51
            #   5: 4x U54, 1x E51
            # The qemu-system-riscv32 sifive_u uses U34/E31 cores
            'cores':    5
        },
        'rpi3': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'raspi3',
            'memory':   1024,
        },
        'spike64': {
            'qemu-bin': 'qemu-system-riscv64',
            'machine':  'spike',
            'cpu':      'rv64',
            'memory':   4095,
        },
        'spike32': {
            'qemu-bin': 'qemu-system-riscv32',
            'machine':  'spike',
            'cpu':      'rv32',
            'memory':   1024,
        },
        'zynq7000': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  'xilinx-zynq-a9',
            'memory':   1024,
            'syslog-uart': 1, # kernel log is on UART1, not UART0
        },
        'zynqmp': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  ['xlnx-zcu102', {
                'secure':         'off',
                'virtualization': 'on',
            }],
            'memory':   4096,
        },
        'zynqmp-qemu-xilinx': {
            'wrapper-class': QEMU_xilinx,
            'memory':   4096,
        },
        'qemu-arm-virt-a15': {
            'qemu-bin': '/opt/hc/bin/qemu-system-arm',
            'machine':  ['virt', {
                'secure':         'off',
                'virtualization': 'on',
                'highmem':        'off',
                'gic-version':    '2',
            }],
            'cpu':      'cortex-a15',
            'memory':   2048,
        },
        'qemu-arm-virt-a53': {
            'qemu-bin':   'qemu-system-aarch64',
            'machine':    ['virt', {
                'secure':         'off',
                'virtualization': 'on',
                'highmem':        'on',
                'gic-version':    '2',
            }],
            'cpu':      'cortex-a53',
            'memory':   3072,
        },
        'qemu-arm-virt-a57': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'virt',
            'cpu':      'cortex-a57',
            'memory':   2048,
        },
        'qemu-arm-virt-a72': {
            'qemu-bin': 'qemu-system-aarch64',
            'machine':  'virt',
            'cpu':      'cortex-a72',
            'memory':   2048,
        },
        'qemu-riscv-virt32': {
            'qemu-bin': 'qemu-system-riscv32',
            'machine':  'virt',
            'cpu':      'rv32', # virt uses rv32gc
            'memory':   3072,
            'cores':    1, # virt supports up to 8 harts
        },
        'qemu-riscv-virt64': {
            'qemu-bin': 'qemu-system-riscv64',
            'machine':  'virt',
            'cpu':      'rv64', # virt uses rv64gc
            'memory':   3072,
            'cores':    1, # virt supports up to 8 harts
        },
    }

    if not target:
        raise Exception('empty QEMU target')

    qemu_cfg = qemu_cfgs.get(target)
    if not qemu_cfg:
        raise Exception(f'unsupported QEMU target: "{target}"')

    # Get (and remove) the wrapper class from the config. Keeping if in the
    # config bring no gain, because we create a instance of this class anyway
    # and pass the remaining config to it.
    wrapper_class = qemu_cfg.pop('wrapper-class', QEMU_AppWrapper)
    assert wrapper_class is not None # this should have picked the default

    # return an instance of the wrapper
    return wrapper_class(qemu_cfg)


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
class Additional_Param_Type(IntEnum):
    VALUE       = 0,
    BINARY_IMG  = 1,


#-------------------------------------------------------------------------------
class QemuProxyRunner():
    # to allow multi instance of this class we need to avoid insisting on the
    # same port. Therefore a base is established here but the port number used
    # is calculated every time an instance gets created (see code below). At the
    # moment we can consider this as a workaround. In the future we will
    # implement a different way of communication for QEMU (see SEOS-1845)
    qemu_uart_network_port  = 4444
    port_cnt_lock = threading.Lock()

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):

        self.generic_runner = generic_runner
        self.run_context = generic_runner.run_context

        # attach to QEMU UART via TCP bridge
        self.bridge = TcpBridge(printer=self.get_printer())

        self.process_qemu = None

        QemuProxyRunner.port_cnt_lock.acquire()
        base_port = QemuProxyRunner.qemu_uart_network_port
        QemuProxyRunner.qemu_uart_network_port += 4
        QemuProxyRunner.port_cnt_lock.release()

        self.qemu_uart_network_port = base_port
        self.proxy_network_port     = base_port + 1

        self.qemu_uart_log_host     = 'localhost'
        self.qemu_uart_log_port     = base_port + 2


    #---------------------------------------------------------------------------
    def get_printer(self):
        if not self.run_context:
            return None

        return self.run_context.printer


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.get_printer()
        if printer:
            printer.print(msg)


    #---------------------------------------------------------------------------
    def is_qemu_running(self):
        return self.process_qemu and self.process_qemu.is_running()


    #---------------------------------------------------------------------------
    def send_data_to_uart(self, data):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.qemu_uart_log_host, self.qemu_uart_log_port))
            s.sendall(str.encode(data))


    #---------------------------------------------------------------------------
    def send_file_to_uart(self, file):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.qemu_uart_log_host, self.qemu_uart_log_port))
            with open(file, 'r') as srec:
                while True:
                    srec_line = srec.readline()
                    if len(srec_line) == 0:
                        break
                    else:
                        for byte in srec_line:
                            s.send(bytes(byte, 'ascii'))
                            # Empirically set delay between individual bytes
                            # long enough to eliminate transmission errors
                            time.sleep(0.01)

                    # Empirically set delay between individual records
                    # long enough to eliminate transmission errors
                    time.sleep(0.15)


    #---------------------------------------------------------------------------
    def start_qemu(self):

        assert not self.is_qemu_running()
        qemu = get_qemu(
                target  = self.run_context.platform,
                printer = self.get_printer())
        assert qemu is not None # this should have raised an exception

        # QEMU debug log: -d <option,option...> -D <logfile>
        #
        #   tid
        #       new in v7.1, separate logs per CPU (use „-D logfile-%d“)
        #   in_asm
        #       show assembly (one for each compiled TB, use "-singelstep")
        #       if v7.1 just says "OBJD-T: 73c23f91", then QEMU lacks
        #       libcapstone support to see "add x19, x19, #0xff0"
        #   nochain
        #       don't chain compiled TBs
        #   exec
        #       show each executed TB (and the CPU ID)
        #       Trace <CPU-ID>: <tb> [<tb->tc.ptr>/<pc>/<tb-flags>/<tb-flags>] <symbol>
        #   int
        #       show interrupts/exceptions
        #   cpu
        #       show CPU registers before entering a TB
        #   unimp
        #       log unimplemented functionality
        #   guest_errors
        #       log invalid operations

        #qemu.config['singlestep'] = True
        #qemu.add_params('-d', 'in_asm,nochain') # logged to stderr
        #qemu.add_params('-d', 'in_asm,exec,nochain') # logged to stderr
        #qemu.add_params('-D', 'qemu_log.txt')

        # specific setup
        qemu.setup(self.run_context)

        platform = self.run_context.platform
        machine = qemu.get_machine()

        # Set default images
        if platform in [
            'hifive',
            'migv_qemu',
            'qemu-riscv-virt64',
            'qemu-riscv-virt32',
        ]:
            qemu.config['bios'] = self.run_context.system_image
        else:
            # Seems older QEMU versions do not support the 'bios' parameter, so
            # we can't use
            #   qemu.bios = self.run_context.system_image
            # and have to stick to loading a kernel
            qemu.config['kernel'] = self.run_context.system_image

        # Serial port usage is platform specific. On platforms with one serial
        # port only, this one is used for syslog. If there are multiple UARTs,
        # some platforms have the syslog on UART_0 and UART_1 is available for
        # data exchange. Others do it the other way around, UART_0 is available
        # for data exchange and UART_1 is used for the syslog.
        has_syslog_on_uart_1 = (1 == qemu.config['syslog-uart'])
        has_data_uart = (platform in [
                            'sabre',
                            'zynq7000',
                            'zynqmp',
                            'zynqmp-qemu-xilinx',
                            'hifive',
                        ])
        assert 0 == len(qemu.config['serial_ports'])
        if not has_syslog_on_uart_1:
            # UART 0 is syslog
            qemu.sys_log_setup(
                self.generic_runner.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                0)

        print("Temporary fix set has data uart to false")
        has_data_uart = False

        if (has_data_uart):
            print("HAS DATA UART!\n\n\n")
            # UART 0 or UART 1 is used for data
            qemu.add_serial_port(f'tcp:localhost:{self.qemu_uart_network_port},server')
        #elif has_syslog_on_uart_1:
        #    # UART 0 must be a dummy in this case
        #    assert 0 == len(qemu.serial_ports)
        #    qemu.add_serial_port('null')

        # This works data is received
        qemu.add_serial_port(f"tcp:localhost:{7000},server=on,wait=off")
        #qemu.add_serial_port("pty")

        if has_syslog_on_uart_1:
            assert 1 == len(qemu.config['serial_ports'])
            # UART 1 is syslog
            qemu.sys_log_setup(
                self.generic_runner.system_log_file.name,
                self.qemu_uart_log_host,
                self.qemu_uart_log_port,
                1)


        # setup NICs
        if platform in [
            'sabre',
            'zynq7000',
        ]:
            # The Proxy uses tap1 to provide a network channel, so we use tap2
            # here for the native networking.
            qemu.add_nic_tap('tap2')

        elif platform in [
            'zynqmp',
            'zynqmp-qemu-xilinx',
        ]:
            # There are 4 network ports (GEM0-3). In the zcu102 hardware, only
            # GEM3 has a physical network port attached. There seem no way in
            #QEMU to connect only GEM3, we have to connect GEM0-2 also. We can't
            # use the 'none' type and must even give a proper model. That leaves
            # now choice but make it a 'user' NIC then (which is the default
            # that QEMU uses if no type is given).
            qemu.add_nic('user', {'model': 'cadence_gem'})
            qemu.add_nic('user', {'model': 'cadence_gem'})
            qemu.add_nic('user', {'model': 'cadence_gem'})
            qemu.add_nic_tap('tap2', {'model': "cadence_gem"})

        elif (machine == 'virt') and qemu.config['cpu'].startswith('cortex-a'):
            # Avoid an error message on the ARM virt platform that the
            # device "virtio-net-pci" init fails due to missing ROM file
            # "efi-virtio.rom".
            qemu.add_nic('none')


        # setup SD Card
        if isinstance(qemu, QEMU_xilinx):
            # QEMU boots with ATF and and special U-Boot version, that loads
            #  the system from the SD card's file os_image.elf.
            qemu.config['kernel'] = None
            log_dir = self.run_context.log_dir
            sd_card_image = os.path.join(log_dir, 'sdcard1.img')
            # ToDo: 128 MiB seems a lot if we just store os_image.elf there.
            tools.create_sd_img(
                sd_card_image,
                128*1024*1024, # 128 MiB
                [(self.run_context.system_image, 'os_image.elf')])
            qemu.add_sdcard_from_image(sd_card_image)

        elif self.run_context.sd_card_size and (self.run_context.sd_card_size > 0):
            # If the test framework is invoked with an SD card image, but the
            # emulated machine does not support SD cards, we just ignore the
            # SD card and continue, as the platform specific system might not
            # need it and use some other storage instead. It might be better to
            # fail here and refactor things, so the test gets a way to handle
            # this, e.g. by setting a flag to ignore this parameter or just
            # remove/clear the parameter.
            if machine in [
                'spike',
                'sifive_u',
                'mig-v',
                'virt'
            ]:
                self.print(f'QEMU: ignoring SD card image, not supported for {machine}')
            else:
                sd_card_image = os.path.join(self.run_context.log_dir, 'sdcard1.img')
                # ToDo: maybe we should create a copy here and not
                #       modify the original file...
                with open(sd_card_image, 'wb') as f:
                    f.truncate(self.run_context.sd_card_size)
                qemu.add_sdcard_from_image(sd_card_image)


        # start QEMU
        qemu_proc = qemu.start(
                        log_file_stdout = self.generic_runner.get_log_file_fqn('qemu_out.txt'),
                        log_file_stderr = self.generic_runner.get_log_file_fqn('qemu_err.txt'),
                        additional_params = self.run_context.additional_params,
                        printer = self.get_printer(),
                        print_log = self.run_context.print_log)
        assert qemu_proc is not None # this should have raised an exception
        self.process_qemu = qemu_proc

        if self.run_context.print_log:
            # Now that a QEMU process exists, start the monitor thread. The
            # checker function ensures it automatically terminates when the
            # QEMU process terminates.
            self.generic_runner.system_log_file.start_monitor(
                printer = self.get_printer(),
                checker_func = lambda: self.is_qemu_running()
            )

        # QEMU is starting up now. If some output is redirected to files, these
        # files may not exist until there is some actual output written. There
        # is not much gain if we sleep now hoping the files pop into existence.
        # The users of these files must handle the fact that they don't exist
        # at first and pop into existence eventually

        if has_data_uart:
            # Starting a TCP server that connects to QEMU's serial port. It
            # depends on the system load how long the QEMU process itself takes
            # to start and when QEMU's internal startup is done, so it is
            # listening on the port. Tests showed that without system load,
            # timeouts are rarely needed, but once there is a decent system
            # load, even 500 ms may not be enough. With 5 seconds we should be
            # safe.
            self.bridge.connect_to_server(
                '127.0.0.1',
                self.qemu_uart_network_port,
                5)


    #----------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        self.start_qemu()

        # we used to have a sleep() here to give the QEMU process some fixed
        # time to start, the value was based on trial and error. However, this
        # did not really address the core problem in the end. The smarter
        # approach is forcing everybody interacting with QEMU to come up with
        # a specific re-try concept and figure out when to give up. This is
        # also closer to dealing with physical hardware, where failures and
        # non-responsiveness must be taken into account anywhere.

        if self.run_context.use_proxy:
            # Start the bridge between QEMU and the Proxy.
            self.bridge.start_server(self.proxy_network_port)
            # Start the proxy
            self.generic_runner.startProxy(
                connection = f'TCP:{self.proxy_network_port}',
                enable_tap = True,
            )


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.bridge.stop_server()
        if self.is_qemu_running():
            #self.print('terminating QEMU...')
            self.process_qemu.terminate()
            self.process_qemu = None


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.bridge.shutdown()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def get_serial_socket(self):
        return None if self.generic_runner.is_proxy_running() \
               else self.bridge.get_source_socket()


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return QemuProxyRunner(generic_runner)
