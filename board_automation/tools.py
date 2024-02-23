#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import sys
import traceback
import os
import pathlib
import socket
import threading
import time
import datetime
import subprocess
from . import line_reader

#-------------------------------------------------------------------------------
# implement "@class_or_instancemethod" attribute for methods
class class_or_instance_method(classmethod):

    def __get__(self, instance, type_):

        descr_get = super().__get__ if instance is None \
                    else self.__func__.__get__

        return descr_get(instance, type_)


#-------------------------------------------------------------------------------
def add_subdir_to_sys_path(path, subdir):
    sys.path.append(
        os.path.join(
            str(pathlib.Path(path).parent.absolute()),
            subdir
        )
    )


#-------------------------------------------------------------------------------
def print_files_from_folder(folder):

    filenames = os.listdir(folder)

    for f in filenames:
        fqn = os.path.join(folder, f)
        stat_info = os.lstat(fqn)
        time_str = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.gmtime(stat_info.st_mtime))

        print(f'  {stat_info.st_size:8d}   {time_str}   {f}')


#-------------------------------------------------------------------------------
def get_mountpoints():

    def parse_mntpt(line):
        dev, mntpt, _ = line.split(None, 2)
        return dev, mntpt

    with open('/proc/mounts') as f:
        return dict(map(parse_mntpt, f.readlines()))


#-------------------------------------------------------------------------------
def get_mountpoint_for_dev(dev):

    mntpts = get_mountpoints()
    return mntpts.get(dev)


#-------------------------------------------------------------------------------
def get_disk_id_for_dev(dev):
    folder = '/dev/disk/by-id'

    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def get_disk_path_for_dev(dev):

    # for dev, mp in mntpts.items(): print('{} -> {}'.format(dev, mp))

    folder = '/dev/disk/by-path'
    # contains things like
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0-part1 -> ../../sda1
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0 -> ../../sda
    #
    # check for pattern: <buf>-usb-<path>-scsi-<path>[-<id>]


    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def find_usb_by_serial(serial):

    base_dir = '/sys/bus/usb/devices'

    print(f'check {base_dir} for serial: {serial}')

    def get_id(dn, id_file):
        file_name = os.path.join(dn, id_file)
        if not os.path.exists(file_name): return None
        with open(file_name) as f:
            return f.read().strip()

    for usbid in os.listdir(base_dir):
        dn = os.path.join(base_dir, usbid)
        if (serial == get_id(dn, 'serial')):
            vid = get_id(dn, 'idVendor')
            pid = get_id(dn, 'idProduct')
            print(f'  {vid}:{pid} at {dn}')
            # no break here, serial may not be unique


#-------------------------------------------------------------------------------
def create_sd_img(sd_img_path, sd_img_size, sd_content_list = []):
    # Create SD image file
    #   - Create a binary file and truncate to the received size.
    with open(sd_img_path, "wb") as sd_image_file:
        sd_image_file.truncate(sd_img_size)

    # Format SD to a FAT32 FS
    subprocess.check_call(['mkfs.fat', '-F', '32', sd_img_path])

    # Copy items to SD image:
    #   - sd_content_list is a list of tuples: (HOST_OS_FILE_PATH, SD_FILE_PATH).
    #   - mcopy (part of the mtools package) copies the file from the linux host
    #     to the SD card image without having to mount the SD card first.
    for item in sd_content_list:
        subprocess.check_call([
            'mcopy',
            '-i',
            sd_img_path,
            item[0],
            os.path.join('::/', item[1])])


#===============================================================================
#===============================================================================
class MyThread(threading.Thread):
# This is a convenience wrapper class for using threads. It reports exceptions
# in the thread's main function that would otherwise get lost. Furthermore it
# allows passing a context to the thread.
# Python recommends using daemon threads, because many common use case are
# basically starting worker threads that can be killed when the application
# terminated. Use cases for non-deamon threads are more rare, but they allow
# better control to do proper cleanup and shutdown.
#
# The manual way with threads is:
#
#   import threading
#   ...
#   def some_method(self, params):
#      ...
#      def my_thread():
#          do_something_special(...)
#
#      thread = threading.Thread(target = my_thread, daemon = True)
#      thread.start()
#
# With this wrapper it becomes:
#
#   import tools
#   ...
#   def some_method(self, params, ctx):
#      ...
#      my_context = ...
#      ...
#      def my_thread(thread):
#          the_ctx = thread.ctx
#          self.do_something_special(...)
#
#      thread = tools.run_in_thread(my_thread, ctx)

    #---------------------------------------------------------------------------
    def __init__(self, func, ctx=None, isDaemon=None):
        super().__init__(daemon=isDaemon)
        self._func = func
        self.ctx  = ctx


    #---------------------------------------------------------------------------
    def __str__(self):
        return f'{self.name}/{self._func.__name__}()'


    #---------------------------------------------------------------------------
    def run(self):
        try:
            # ToDo: could use inspect.signature(self._func) to find out how
            #       man parameters the function can take and then choose between
            #       calling self._func() or self._func(self) or
            #       self._func(self, self.ctx) for further convenience.
            self._func(self)
        except: # catch really *all* exceptions
            (e_type, e_value, e_tb) = sys.exc_info()
            print(f'EXCEPTION in thread {self}: ' +
                  ''.join(traceback.format_exception_only(e_type, e_value)) +
                  ''.join(traceback.format_tb(e_tb)))


#-------------------------------------------------------------------------------
def run_in_thread(func, ctx=None, isDaemon=True):
    t = MyThread(func, ctx=ctx, isDaemon=isDaemon)
    t.start()
    return t


#===============================================================================
#===============================================================================

class PrintSerializer():

    #---------------------------------------------------------------------------
    def __init__(self):
        self.lock = threading.Lock()


    #---------------------------------------------------------------------------
    def print(self, msg):

        with self.lock:
            # msg = '[{}] {}'.format(
            #         msg,
            #         datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
            print(msg)


#===============================================================================
#===============================================================================

class Timeout_Checker():

    #---------------------------------------------------------------------------
    # any value less than 0 or None means infinite, the value 0 indicates a zero
    # timeout, ie. "do not block".
    def __init__(self, timeout_sec):

        self.time_end = \
            timeout_sec.time_end if isinstance(timeout_sec, Timeout_Checker) \
            else None if (timeout_sec is None) or (timeout_sec < 0) \
            else time.time() + timeout_sec


    #---------------------------------------------------------------------------
    def __str__(self):
        return 'Timeout: ' + (
                    'infinite' if self.is_infinite() \
                    else f'{self.get_remaining()} sec')


    #---------------------------------------------------------------------------
    @classmethod
    def infinite(cls):
        return cls(-1)


    #---------------------------------------------------------------------------
    def is_infinite(self):
        return (self.time_end is None)


    #---------------------------------------------------------------------------
    # Returns a value greater zero if time left, zero if the timeout has been
    # reached or a negative value if the timeout is infinite.
    def get_remaining(self):

        if self.is_infinite():
            return -1

        time_now = time.time()
        return (self.time_end - time_now) if (self.time_end > time_now) else 0


    #---------------------------------------------------------------------------
    def has_expired(self):
        v = self.get_remaining()
        assert( (v == -1 and self.is_infinite()) or (v >= 0))
        return (0 == v)


    #---------------------------------------------------------------------------
    # Returns a Timeout_Checker instance covering up to the given number of
    # seconds, where timeout_sec can be a value or another Timeout_Checker
    # instance. Any value passed for timeout_sec that is less than 0 or None
    # means infinite. The timeout cannot exceed the amount of time left in
    # parent's timeout, but it can be infinite if the parent's timeout is
    # infinite.
    def sub_timeout(self, timeout_sec):

        sub_timeout = Timeout_Checker(timeout_sec)

        # If we are an infinite timeout, we can can guarantee anything,
        # otherwise we must cut the timeout at our own timeout and basically
        # return a clone of us.
        if not self.is_infinite() \
           and (sub_timeout.is_infinite() \
                or (sub_timeout.get_remaining() > self.get_remaining())):
            return Timeout_Checker(self)

        return sub_timeout


    #---------------------------------------------------------------------------
    # Sleep either for the given time, if this is less than the remaining time
    # in our timeout. Otherwise sleep for the remaining time in our timeout
    # only. The parameter timeout can hold a value of another Timeout_Checker
    # instance.
    def sleep(self, timeout):

        # We don't handle None as 0, because if we see None here this is likely
        # a bug in the caller's code.
        if (timeout is None):
            raise Exception('can''t sleep() for timeout "None"')

        # Passing negative values is likely a bug in the caller's code.
        if not isinstance(timeout, Timeout_Checker) and (timeout < 0):
            raise Exception('can''t sleep() for negative timeouts')

        sub_timeout = self.sub_timeout(timeout)

        # Waiting an infinite time when we have an infinite timeout is not
        # supported, because this is likely a bug in the caller's code.
        if sub_timeout.is_infinite():
            assert(self.is_infinite())
            raise Exception('can''t sleep() for an infinite time')

        # get the timeout, sleep only if it has not already expired
        timeout_sec = sub_timeout.get_remaining()
        if (0 != timeout_sec):
            time.sleep(timeout_sec)


#===============================================================================
#===============================================================================

class Log_File():

    #---------------------------------------------------------------------------
    def __init__(self, name):
        self.name = name
        self.monitor_thread = None


    #---------------------------------------------------------------------------
    # this return a generator build on top of Stream_Line_Reader
    def get_line_reader(self, timeout = None, checker_func = None):
        return line_reader.File_Line_Reader(
                    fileName = self.name,
                    timeout = timeout,
                    checker_func = checker_func)


    #---------------------------------------------------------------------------
    # Open the file in for reading in non-blocking mode. If the file does not
    # exist, sleep a while unless timeout and try again. The function returns a
    # file handle or 'None' on timeouts. It can raise exceptions on fatal
    # errors.
    def open_non_blocking(self, timeout = None):
        line_reader = self.get_line_reader(timeout = timeout)
        while True:
            stream = line_reader.open_stream()
            if stream is not None:
                assert not stream.closed
                return stream

            if not line_reader.wait():
                return None


    #---------------------------------------------------------------------------
    def start_monitor(
            self,
            printer,
            checker_func = None):

        # The line reader uses an infinite timeout by default.
        log = self.get_line_reader(checker_func = checker_func)

        # Monitoring runs in a separate thread. The log file may not even exist,
        # it gets created when data is written to it. The line reader can handle
        # this case.
        # Unfortunately, there is a line break bug in some logs, where "\n\r"
        # (LF+CR) is used instead of "\r\n" (CR+LF). Universal newline handling
        # only considers "\r", "\n" and "\r\n" as line break, thus "\n\r" is
        # taken as two line breaks and we see a lot of empty lines in the logs.

        def monitoring_thread(thread):
            start = datetime.datetime.now()
            for line in log:
                delta = datetime.datetime.now() - start
                if line.endswith('\n'):
                    line = line.rstrip('\n')
                printer.print(f'[{delta}] {line}')

        self.monitor_thread = run_in_thread(monitoring_thread)
