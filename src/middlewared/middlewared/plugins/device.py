import gevent
import shlex
import socket
import time

from middlewared.schema import accepts, Str
from middlewared.service import Service

from bsd import devinfo


class DeviceService(Service):

    @accepts(Str('type', enum=['SERIAL']))
    def get_info(self, _type):
        """
        Get info for certain device types.

        Currently only SERIAL is supported.
        """
        return getattr(self, f'_get_{_type.lower()}')()

    def _get_serial(self):
        ports = []
        for devices in devinfo.DevInfo().resource_managers['I/O ports'].values():
            for dev in devices:
                if not dev.name.startswith('uart'):
                    continue
                ports.append({
                    'name': dev.name,
                    'description': dev.desc,
                    'drivername': dev.drivername,
                    'location': dev.location,
                    'start': hex(dev.start),
                    'size': dev.size
                })
        return ports


def devd_loop(middleware):
    while True:
        try:
            devd_listen(middleware)
        except OSError:
            middleware.logger.warn('devd pipe error, retrying...', exc_info=True)
            time.sleep(1)


def devd_listen(middleware):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    s.connect('/var/run/devd.seqpacket.pipe')
    while True:
        line = s.recv(8192)
        if line is None:
            break
        line = line.decode(errors='ignore')
        if not line.startswith('!'):
            # TODO: its not a complete message, ignore for now
            continue

        try:
            parsed = middleware.threaded(lambda l: dict(t.split('=') for t in shlex.split(l)), line[1:])
        except ValueError:
            middleware.logger.warn(f'Failed to parse devd message: {line}')
            continue

        if 'system' not in parsed:
            continue

        # Lets ignore CAM messages for now
        if parsed['system'] == 'CAM':
            continue

        middleware.send_event(
            f'devd.{parsed["system"]}'.lower(),
            'ADDED',
            data=parsed,
        )


def setup(middleware):
    gevent.spawn(devd_loop, middleware)