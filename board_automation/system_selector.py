#!/usr/bin/python3

from . import tools
from . import board_automation
from . import automation_QEMU
from . import automation_SabreLite
from . import automation_SabreLite_boardSetup
from . import automation_RasPi
from . import automation_RasPi_boardSetup
from . import automation_zcu102


#-------------------------------------------------------------------------------
def get_test_runner(
        log_dir,
        resource_dir,
        platform,
        system_image,
        proxy_config,
        sd_card_size,
        additional_params = None,
        print_log = False ):

    # translate generic platform names
    if (platform == 'spike'):
        print('translating PLATFORM: spike -> spike64')
        platform = 'spike64'

    run_context = board_automation.Run_Context(
                    log_dir,
                    resource_dir,
                    platform,
                    system_image,
                    sd_card_size,
                    tools.PrintSerializer(),
                    print_log)

    if (platform in [
            'sabre',
            'zynqmp',
            'zynq7000',
            'spike32',
            'spike64',
            'hifive']):
        return automation_QEMU.QemuProxyRunner(
                        run_context,
                        proxy_config,
                        additional_params)

    if (platform == 'sabre-hw'):
        return automation_SabreLite.BoardRunner(
                        run_context,
                        automation_SabreLite_boardSetup.Board_Setup(
                            run_context.printer))

    if (platform == 'rpi3'):
        return automation_RasPi.BoardRunner(
                        run_context,
                        automation_RasPi_boardSetup.Board_Setup(
                            run_context.printer))

    if (platform in [
            'migv',
            'migv',
            'zcu102']):
        return automation_zcu102.BoardRunner(
                        run_context,
                        additional_params)

    raise Exception('unsupported platform: {}'.format(platform))
