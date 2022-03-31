import logs


#-------------------------------------------------------------------------------
def run_test_log_match_sequence(fixture, test_system, expr_array, timeout_sec=0):
    """will take an array of regular expressions and perform the simple test.
    The order of the elements in the array matters, must be the same order in
    the log file"""

    # ToDo: this starts the system if it is not already running. We should have
    #       a check here if the boot itself went well, so we don't count this
    #       time against the actual test. Also, if the boot fails, we can abort
    #       the test early already and do not wait the full test specific
    #       timeout.
    test_runner = fixture(test_system)

    (ret, text, expr_fail) = logs.check_log_match_sequence(
                                test_runner.get_system_log(),
                                expr_array,
                                timeout_sec)

    if not ret:
        raise Exception(" missing: %s"%(expr_fail))


#-------------------------------------------------------------------------------
def run_test_log_match_set(fixture, test_system, expr_array, timeout_sec=0):
    """will take an array of regular expressions and perform the simple test.
    The order of the elements in the array does not matter, the matches just
    have to be there in the log occurring at any time at the least once per
    single expression"""

    # ToDo: this starts the system if it is not already running. We should have
    #       a check here if the boot itself went well, so we don't count this
    #       time against the actual test. Also, if the boot fails, we can abort
    #       the test early already and do not wait the full test specific
    #       timeout.
    test_runner = fixture(test_system)

    (ret, text, expr_fail) = logs.check_log_match_set(
                                test_runner.get_system_log(),
                                expr_array,
                                timeout_sec)
    if not ret:
        raise Exception(" missing: %s"%(expr_fail))


#-------------------------------------------------------------------------------
def run_test_log_match(fixture, test_system, expr, timeout_sec=0):
    """performs the simplest test by getting the log file from the fixture and
    then assert the match of the regular expression in a line of the log"""

    return run_test_log_match_set(fixture, test_system, [expr], timeout_sec)
