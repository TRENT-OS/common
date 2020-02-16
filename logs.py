"""
Logs parser

This module allows the user to parse a log searching in it in a way that is
useful for testing. Such operations like looking for a regex match are
performed "online" on the log until the match condition happens or a timeout
occurred
"""

import time
import re
import fcntl
import os


#------------------------------------------------------------------------------
def get_match_in_line(f, regex, timeout_sec=0):
    """
    Gets the first regex match in a text file parsing it line by line.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    regex(Pattern): a compiled regular expression to look for
    timeout_sec(int, optional): timeout in seconds, 0 means forever

    Returns:
    text(str): the text from the begin of the search until the first match or the end
    match(str): the matching string
    """

    start   = time.time()

    text    = ""
    line    = ""

    # there is a line break bug in some logs, "\n\r" is used instead of
    # "\r\n"- Universal newline handling accepts "\r", "\n" and "\r\n"
    # as line break. We end up with some empty lines then as "\n\r" is
    # taken as two line breaks.

    while True:

        # readline() will return a string, which is terminated by "\n" for
        # every line. For the last line of the file my may return a string
        # that is not terminated by "\n" to indicate the end of the file. If
        # another task is appending data to the file, readline() may return
        # multiple strings without "\n", each containing the new data written
        # to the file.
        #
        #  loop iteration n:  | line part |...
        #  loop iteration n+1             | line part |...
        #  loop iteration n+2                         | line+\n |

        line += f.readline()
        is_complete_line = line.endswith("\n")
        if is_complete_line:
            text += line
            mo = regex.search(line)
            if mo: return (text, mo.group(0))
            line = ""

        # timout=0 mean there is no timeout
        if ((timeout_sec != 0) and (time.time() - start > timeout_sec)):
            return (text, None)

        if not is_complete_line:
            # we have eached the end of the file, wait a bit and then check
            # again if new data has bee appended to the file
            time.sleep(0.5)


#------------------------------------------------------------------------------
def open_file_non_blocking(file_name, mode, newline=None):
    """
    Opens a file and set non blocking OS flag

    Args:
    file_name(str): the file full path
    mode: mode to pass to open()
    nl(str, optional): newline

    Returns:
    f(file): the file object
    """

    f = open(file_name, mode, newline=newline)
    fd = f.fileno()
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)

    return f

