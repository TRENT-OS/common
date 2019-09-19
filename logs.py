""" Logs parser

This module allows the user to parse a log searching in it in a way that is
useful for testing. Such operations like looking for a regex match are
performed "online" on the log until the match condition happens or a timeout
occurred

"""

import time
import re
import fcntl
import os

def get_match_in_line(f, regex, timeout_sec=0):
    """ Gets the first regex match in a text file parsing it line by line.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    regex(Pattern): a compiled regular expression to look for
    timeout_sec(int, optional): timeoiut in seconds, 0 means forever

    Returns:
    text(str): the text from the begin of the search until the first match or the end
    match(str): the matching string

    """

    start   = time.time()

    cont    = True
    text    = ""
    mo      = None
    line    = ""

    while cont:
        line += f.readline()
        if line.find("\n") >= 0:
            text += line
            mo = regex.search(line)
            line = ""
        cont = ((mo is None) and
                    (timeout_sec == 0 or (time.time() - start <= timeout_sec)))

    match = mo.group(0) if mo is not None else None
    return (text, match)

def open_file_non_blocking(file_name, mode, nl='\r\n'):
    """ Opens a file and set non blocking OS flag

    Args:
    file_name(str): the file full path
    mode: mode to pass to open()
    nl(str, optional): newline

    Returns:
    f(file): the file object

    """

    f = open(file_name, mode, newline=nl)
    fd = f.fileno()
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)

    return f

