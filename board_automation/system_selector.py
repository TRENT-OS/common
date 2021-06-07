#!/usr/bin/python3

from . import tools
from . import board_automation
from . import automation_QEMU
from . import automation_SabreLite
from . import automation_SabreLite_boardSetup
from . import automation_RasPi
from . import automation_RasPi_boardSetup


#-------------------------------------------------------------------------------
def get_test_runner(
        log_dir,
        resource_dir,
        platform,
        system_image,
        proxy_config,
        sd_card_size,
        print_log = False ):

    run_context = board_automation.Run_Context(
                    log_dir,
                    resource_dir,
                    platform,
                    system_image,
                    sd_card_size,
                    tools.PrintSerializer(),
                    print_log)

    if (platform in ['sabre', 'zynqmp', 'zynq7000']):
        return automation_QEMU.QemuProxyRunner(
                        run_context,
                        proxy_config)

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

    raise Exception('unsupported platform: {}'.format(platform))
