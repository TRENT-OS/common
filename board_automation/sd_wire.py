#!/usr/bin/python3

import os
import shutil

from . import process_tools
from . import tools
from . import wrapper_pyftdi
from .tools import Timeout_Checker

from pyftdi import ftdi

#===============================================================================
#===============================================================================

class SD_MUX_CTRL_Binary_Wrapper:
    """
    wrapper for the binary control application for SW Wire devices
    """

    #---------------------------------------------------------------------------
    def __init__(self, ctrl_app = None, env = None):
        self.ctrl_app = ctrl_app or 'sd-mux-ctrl'
        self.env = env


    #---------------------------------------------------------------------------
    def cmd(self, params):
        cmd = [self.ctrl_app]
        cmd.extend(params)
        return process_tools.execute_os_cmd(cmd, env = self.env)


    #---------------------------------------------------------------------------
    def list_devices(self):
        print('SD Wire devices (via sd-mux binary)')
        return self.cmd(['-o'])


#===============================================================================
#===============================================================================

class SD_MUX_CTRL_Binary_Wrapper_Device:
    """
    wrapper for controlling a specific device via the control application
    """

    #---------------------------------------------------------------------------
    def __init__(self, serial, binary_wrapper):
        self.serial = serial
        self.binary_wrapper = binary_wrapper


    #---------------------------------------------------------------------------
    def cmd(self, params):

        if self.serial:
            params.extend(['-e', self.serial])

        return self.binary_wrapper.cmd(params)


    #---------------------------------------------------------------------------
    def get_info(self):
        return self.cmd(['-i'])


    #---------------------------------------------------------------------------
    def switch_to_device(self):
        return self.cmd(['-d'])


    #---------------------------------------------------------------------------
    def switch_to_host(self):
        return self.cmd(['-s'])


#===============================================================================
#===============================================================================

class SD_WIRE_Controller:
    #---------------------------------------------------------------------------
    def __init__(self, serial):
        self.serial = serial

        # sd-wire uses a FT200XD, the SD card switch is controlled via CBUS0.
        # There is an EEPROM that makes the chip use a dedicated VID/PID.
        VID_SAMSUNG = 0x04e8 # FT200XD default is 0x0403h (FTDI)
        PID_SD_WIRE = 0x6001 # FT200XD default is 0x6015. FTDI uses PID 0x6001
                             #  for FT232 and FT245

        # register sd-wire device with pyftdi core, so we can use it
        ftdi.Ftdi.add_custom_vendor(VID_SAMSUNG, 'samsung')
        ftdi.Ftdi.add_custom_product(VID_SAMSUNG, PID_SD_WIRE, 'sd_wire')

        url = 'ftdi://0x{:04x}:0x{:04x}:{}/1'.format(
                    VID_SAMSUNG,
                    PID_SD_WIRE,
                    self.serial)
        print('open by URL: {}'.format(url))
        self.cbus_gpio = wrapper_pyftdi.get_pyftdi_cbus_gpio(url)


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def list_devices(self_or_cls):
        print('SD Wire devices (via pyftdi)')
        ftdi.Ftdi.show_devices('ftdi:///?')


    #---------------------------------------------------------------------------
    def switch_to_device(self):
        self.cbus_gpio.write(0)  # set CBUS0 = 0
        return 0


    #---------------------------------------------------------------------------
    def switch_to_host(self):
        self.cbus_gpio.write(1)  # set CBUS0 = 1
        return 0


#===============================================================================
#===============================================================================

class SD_Wire_Device:
    """
    wraps an SD-Wire device
    """
    #---------------------------------------------------------------------------
    def __init__(self, usb_path, vid, pid, serial, usb_path_sd, dev_sd):

        self.usb_path     = usb_path
        self.vid          = vid
        self.pid          = pid
        self.serial       = serial

        self.usb_path_sd  = usb_path_sd
        self.dev_sd       = dev_sd


#===============================================================================
#===============================================================================

class SD_Wire:

    #---------------------------------------------------------------------------
    def __init__(
        self,
        mountpoint,
        serial = None,
        partition = 1,
        usb_path = None,
        ctrl_app = None,
        env = None):

        self.serial = serial
        self.partition = partition
        self.mountpoint = mountpoint

        try:
            if self.serial:
                print('using SW Wire: {}'.format(self.serial))
                self.sd_wire_ctrl = SD_WIRE_Controller(self.serial)

                # sanity check
                self.dev = self.find_by_serial(self.serial)
                if self.dev is None:
                    raise Exception('no sd-wire device found with s/n: {}'.format(self.serial))
                if usb_path and (usb_path != self.dev.usb_path):
                    raise Exception('USB path different, expected {}, got {}'.format(usb_path, self.dev.usb_path))

            elif usb_path:
                raise Exception('implement me')
                #self.dev = self.find_by_ ...
                # look up USB path and check if there's a SD wire device
                if serial and (serial != self.dev.serial):
                    raise Exception('serial number different, expected {}, got {}'.format(serial, self.dev.serial))

            else:
                raise Exception('must specify serial and/or USB path')

        except Exception as e:
            print('EXCEPTION:', e)
            # print what the tools find and what we find. Ideally all outputs
            # show the same devices
            self.list_devices()
            SD_WIRE_Controller.list_devices()
            if ctrl_app:
                sw_wire_app = SD_MUX_CTRL_Binary_Wrapper(ctrl_app, env)
                sw_wire_app.list_devices()

            raise e

        # print('device: {}'.format(self.get_dev_partition()))
        #
        # disk_id = tools.get_disk_id_for_dev(self.get_dev_partition())
        # print('disk ID: {}'.format(disk_id))
        #
        # disk_path = tools.get_disk_path_for_dev(self.get_dev_partition())
        # print('disk path: {}'.format(disk_path))

        # do not switch the SD card to device or host here, but leave it in
        # whatever state it is. The caller shall decide what to do


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def valid_usb_vid_pid(self_or_cls, vid, pid):

        USB_IDs = [ # (VID, PID)
                    ('04e8', '6001')  # VID is Samsung
                  ]

        for (know_vid, known_pid) in USB_IDs:
            if (know_vid == vid) and (known_pid == pid):
                return True

        return False


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def get_devices(self_or_cls):

        dev_list = []

        def get_id_from_file(dn, id_file):
            id_file_fqn = os.path.join(dn, id_file)
            if not os.path.exists(id_file_fqn): return None
            with open(id_file_fqn) as f:
                return f.read().strip()

        def resolve_link(base_dir, filename):
            fqn = os.path.join(base_dir, filename)
            if not os.path.islink(fqn):
                return None
            link = os.readlink(fqn)
            if os.path.isabs(link):
                return link
            return os.path.abspath( os.path.join(base_dir, link) )


        base_folder = '/sys/bus/usb/devices'
        for usb_path in sorted(os.listdir(base_folder)):

            dn = os.path.join(base_folder, usb_path)

            vid = get_id_from_file(dn, 'idVendor')
            pid = get_id_from_file(dn, 'idProduct')
            ser = get_id_from_file(dn, 'serial')

            # print('usb_path: {}:{} {:12} {}'.format(vid, pid, ser or '[none]', usb_path))

            if not self_or_cls.valid_usb_vid_pid(vid, pid):
                continue

            # the switcher is connected to port 2 of the intern hub, the SD
            # card controller is at port 1
            if not usb_path.endswith('.2'):
                continue

            usb_path_sd = '{}.1'.format(usb_path[:-2])
            linked_dev = resolve_link(base_folder, usb_path_sd)
            if linked_dev is None:
                continue

            disk_dev = None
            base_dir_block_devices = '/sys/class/block'
            # since this is sorted, we see /dev/sd[x] before /dev/sd[x][n]
            for dev_block in sorted(os.listdir(base_dir_block_devices)):

                linked_dev2 = resolve_link(base_dir_block_devices, dev_block)
                if linked_dev2 is None:
                    continue

                if not linked_dev2.startswith(linked_dev):
                    continue

                disk_dev = '/dev/{}'.format(dev_block)
                break

            sd_wire_dev = SD_Wire_Device(
                            usb_path,
                            vid,
                            pid,
                            ser,
                            usb_path_sd,
                            disk_dev)

            dev_list.append(sd_wire_dev)

        return dev_list


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def list_devices(self_or_cls):

        print('SD Wire devices')
        for dev in self_or_cls.get_devices():
            print('  {:14} at {} ({}:{} at USB path {})'.format(
                    dev.serial,
                    dev.dev_sd or '[none]',
                    dev.vid,
                    dev.pid,
                    dev.usb_path))


    #---------------------------------------------------------------------------
    @tools.class_or_instance_method
    def find_by_serial(self_or_cls, serial):

        for dev in self_or_cls.get_devices():
            if (dev.serial == serial):
                return dev
        else:
            return None


    #---------------------------------------------------------------------------
    def switch_to_device(self):
        return self.sd_wire_ctrl.switch_to_device()


    #---------------------------------------------------------------------------
    def switch_to_host(self):
        return self.sd_wire_ctrl.switch_to_host()


    #---------------------------------------------------------------------------
    def get_dev_partition(self):
        return '{}{}'.format(self.dev.dev_sd, self.partition)


    #---------------------------------------------------------------------------
    def is_card_present(self):
        # For every SD card reader, the device name (e.g. "/dev/sdb") is fixed
        # when the device is connected. The disk ID for the device is also
        # fixed. Card presence can be found out by asking for a partition's
        # disk ID (e.g. "/dev/sdb1"), this is None if no card is present. A more
        # generic method is checking "/sys/block/<dev>/size", this is 0 if no
        # card is present.
        part = self.get_dev_partition()
        disk_id = tools.get_disk_id_for_dev( part )
        #print('is_card_present: {} is {}'.format(part, disk_id))
        return disk_id is not None


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def wait_card_present(self, timeout_sec = 3):

        timeout = Timeout_Checker(timeout_sec)

        while True:
            if self.is_card_present(): return True
            if timeout.has_expired(): return False
            timeout.sleep(0.2)


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def wait_card_absent(self, timeout_sec = 3):

        timeout = Timeout_Checker(timeout_sec)

        while True:
            if not self.is_card_present(): return True
            if timeout.has_expired(): return False
            timeout.sleep(0.2)


    #---------------------------------------------------------------------------
    def is_card_mounted(self):

        if not self.is_card_present():
            return None

        mp = tools.get_mountpoint_for_dev( self.get_dev_partition() )
        if not mp:
            return None

        if (self.mountpoint and (mp != self.mountpoint)):
            raise Exception('mountpoints differ: {} vs. {}'.format(mp, self.mountpoint))

        return mp


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def wait_card_mounted(self, timeout_sec = 3):

        timeout = Timeout_Checker(timeout_sec)

        while True:
            mp = self.is_card_mounted()
            if mp: return mp
            if timeout.has_expired(): return None
            # poll card state every 200 ms (or less, if not enough time is
            # remaining in the timeout object we got). Reducing the value does
            # not bring much benefit, as is it usually take around 200ms after
            # switching until the card is mounted.
            timeout.sleep(0.2)

    #---------------------------------------------------------------------------
    def unmount(self):

        cmd_arr = ['sync']
        ret = process_tools.execute_os_cmd(cmd_arr)
        if (ret != 0):
            raise Exception('sync failed, code {}'.format(ret), ret)

        cmd_arr = ['umount', self.get_dev_partition()]
        ret = process_tools.execute_os_cmd(cmd_arr)
        if (ret != 0):
            raise Exception('unmount failed, code {}'.format(ret), ret)

    #---------------------------------------------------------------------------
    def automounter(self):

        print('automounter() disabled, tools not in docker container')

        # # https://superuser.com/questions/638225/manually-trigger-automount-in-debian-based-linux
        # #cmd_arr = ['udisks', '--mount', self.get_dev_partition()]

        # cmd_arr = ['udisksctl', 'mount', '-b', self.get_dev_partition()]
        # ret = process_tools.execute_os_cmd(cmd_arr)
        # if (ret != 0):
        #     raise Exception('udisksctl failed, code {}'.format(ret))


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def mount(self, timeout_sec = 5):

        timeout = Timeout_Checker(timeout_sec)

        euid = os.geteuid()
        if 0 != euid:
            raise Exception('need root access rights (uid={}, euid={})'.format(os.getuid(),euid))

        if not self.wait_card_present(timeout):
            raise Exception('SD card partition not present at {}'.format(self.get_dev_partition()))

        mp = self.wait_card_mounted(timeout)
        if mp:
            print('SD card mounted at {}, unmounting for fsck'.format(mp))
            self.unmount()

        self.fsck()

        # try the automounter first, it will block until either (auto-)mounting
        # was successful or there was a failure and we need to do the mounting
        # manually. That's why wait_card_mounted() is called with a zero
        # timeout then, it's supposed to return immediately.
        self.automounter()
        mp = self.wait_card_mounted(timeout_sec = 0)
        if not mp:
            if not self.mountpoint:
                raise Exception('no manual mountpoint defined')
            mp = self.mountpoint

            cmd_arr = ['mount', self.get_dev_partition(), mp]
            ret = process_tools.execute_os_cmd(cmd_arr)
            if (ret != 0):
                raise Exception('mount failed, code {}'.format(ret), ret)

        return mp

    #---------------------------------------------------------------------------
    def fsck(self):
        euid = os.geteuid()
        if (0 != euid):
            raise Exception('need root access rights (uid={}, euid={})'.format(os.getuid(),euid))

        cmd_arr = ['fsck', '-a', self.get_dev_partition()]
        ret = process_tools.execute_os_cmd(cmd_arr)
        if (ret != 0):
            # exit code is build by these bits:
            # 1 - File system errors corrected
            # 2 - System should be rebooted
            # 4 - File system errors left uncorrected
            # 8 - Operational error
            # 16 - Usage or syntax error
            # 32 - Fsck canceled by user request
            # 128 - Shared library error
            ret &= ~0x1  # we expect that error have been corrected
            if (ret != 0):
                raise Exception('fsck failed, code {}'.format(ret), ret)


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def switch_to_device_wait_absent(self, timeout_sec = 5):

        timeout = Timeout_Checker(timeout_sec)

        ret = self.switch_to_device()
        if (ret != 0):
            raise Exception('switch_to_device() failed, code {}'.format(ret))

        # wait for card becoming absent if there is a timeout
        print('wait until SD card is absent')
        if not self.wait_card_absent(timeout):
            raise Exception('SD card partition still present at {}'.format(self.get_dev_partition()))


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def unmount_and_switch_to_device(self, timeout_sec = 5):

        timeout = Timeout_Checker(timeout_sec)

        print('unmount SD card and switch to device')
        self.unmount()
        self.switch_to_device_wait_absent(timeout)


    #---------------------------------------------------------------------------
    # timeout can be an integer or a Timeout_Checker object
    def switch_to_host_and_mount(self, timeout_sec = 5):

        timeout = Timeout_Checker(timeout_sec)

        print('switch SD card to host')
        # the card will be mounted automatically if auto-mounting is enabled
        ret = self.switch_to_host()
        if (ret != 0):
            raise Exception('switch_to_host() failed, code {}'.format(ret))

        print('mount SD card')
        return self.mount(timeout)


    #---------------------------------------------------------------------------
    def copy_file_to_card(self, filename):

        print('copy to card: {}'.format(filename))

        mp = self.is_card_mounted()
        if not mp:
            raise Exception('SD card partition {} not mounted at {}'.format(self.get_dev_partition(), mp))

        if not os.path.isfile(filename):
            raise Exception('file no found: {}'.format(filename))

        if not shutil.copy2(filename, mp):
            raise Exception('could not copy file to SD card: {}'.format(filename))

