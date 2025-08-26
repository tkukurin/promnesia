from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from subprocess import check_call, run

SYSTEM = platform.system()
UNSUPPORTED_SYSTEM = RuntimeError(f'Platform {SYSTEM} is not supported yet!')
NO_SYSTEMD = RuntimeError('systemd not detected, find your own way to start promnesia automatically')

from ..common import root, logger
from ..server import setup_parser as server_setup_parser

SYSTEMD_TEMPLATE = '''
[Unit]
Description=Promnesia browser extension backend

[Install]
WantedBy=default.target

[Service]
ExecStart={launcher} {extra_args}
Type=simple
Restart=always
'''

LAUNCHD_TEMPLATE = '''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
        <dict>
                <key>Label</key>
                <string>{service_name}</string>

                <key>ProgramArguments</key>
                <array>
{arguments}
                </array>

                <key>RunAtLoad</key>
                <true/>
                <key>KeepAlive</key>
                <true/>
        </dict>
</plist>
'''


def systemd(*args: str | Path, method=check_call) -> None:
    method(['systemctl', '--no-pager', '--user', *args])


def install_systemd(name: str, out: Path, launcher: str, largs: list[str]) -> None:
    unit_name = name

    import shlex

    extra_args = ' '.join(shlex.quote(str(a)) for a in largs)

    out.write_text(
        SYSTEMD_TEMPLATE.format(
            launcher=launcher,
            extra_args=extra_args,
        )
    )

    try:
        systemd('stop', unit_name, method=run)  # ignore errors here if it wasn't running in the first place
        systemd('daemon-reload')
        systemd('enable', unit_name)
        systemd('start', unit_name)
        systemd('status', unit_name)
    except Exception as e:
        print(f"Something has gone wrong... you might want to use 'journalctl --user -u {unit_name}' to investigate", file=sys.stderr)
        raise e


def install_launchd(name: str, out: Path, launcher: str, largs: list[str]) -> None:
    service_name = name
    arguments = '\n'.join(f'<string>{a}</string>' for a in [launcher, *largs])
    out.write_text(
        LAUNCHD_TEMPLATE.format(
            service_name=service_name,
            arguments=arguments,
        )
    )
    cmd = ['launchctl', 'load', '-w', str(out)]
    print('Running: ' + ' '.join(cmd), file=sys.stderr)
    check_call(cmd)

    time.sleep(1)  # to give it some time? not sure if necessary
    check_call(f'launchctl list | grep {name}', shell=True)


def install(args: argparse.Namespace) -> None:
    name = args.name
    # todo use platformdirs for config dir detection
    if SYSTEM == 'Linux':
        # Check for existence of systemd
        # https://www.freedesktop.org/software/systemd/man/sd_booted.html
        if not Path('/run/systemd/system/').exists():
            raise NO_SYSTEMD
        suf = '.service'
        if Path(name).suffix != suf:
            name = name + suf
        out = Path(f'~/.config/systemd/user/{name}')
    elif SYSTEM == 'Darwin':  # osx
        out = Path(f'~/Library/LaunchAgents/{name}.plist')
    else:
        raise UNSUPPORTED_SYSTEM
    out = out.expanduser()
    print(f"Writing launch script to {out}", file=sys.stderr)

    # ugh. we want to know whether we're invoked 'properly' as an executable or ad-hoc via scripts/promnesia
    extra_exe: list[str] = []
    if os.environ.get('DIRTY_RUN') is not None:
        launcher = str(root() / 'scripts/promnesia')
    else:
        launcher = sys.executable
        extra_exe = ['-m', 'promnesia']

    db = args.db
    largs = [
        *extra_exe,
        'serve',
        *([] if db is None else ['--db', str(db)]),
        '--timezone', args.timezone,
        '--host', args.host,
        '--port', args.port,
    ]  # fmt: skip

    out.parent.mkdir(parents=True, exist_ok=True)  # sometimes systemd dir doesn't exist
    if SYSTEM == 'Linux':
        install_systemd(name=name, out=out, launcher=launcher, largs=largs)
    elif SYSTEM == 'Darwin':
        install_launchd(name=name, out=out, launcher=launcher, largs=largs)
    else:
        raise UNSUPPORTED_SYSTEM


def setup_parser(p: argparse.ArgumentParser) -> None:
    if SYSTEM == 'Linux':
        dflt = 'promnesia.service'
    elif SYSTEM == 'Darwin':
        dflt = 'com.github.karlicoss.promnesia'
    else:
        # defensive here because setup_parser is called regardless whether the functionality is used
        dflt = NotImplemented

    p.add_argument('--name', type=str, default=dflt, help='Systemd/launchd service name')
    p.add_argument('--unit-name', type=str, dest='name', help='DEPRECATED, same as --name')
    
    # Set default to show help (consistent with config and doctor commands)
    p.set_defaults(func=lambda *_args: p.print_help())
    
    # Add subcommands for service management
    subparsers = p.add_subparsers(dest='service_command', help='Service management commands')
    
    # Install command (requires explicit invocation)
    install_parser = subparsers.add_parser('install', help='Install service')
    server_setup_parser(install_parser)
    install_parser.set_defaults(func=install)
    
    # Management commands
    subparsers.add_parser('start', help='Start service').set_defaults(func=start_service)
    subparsers.add_parser('stop', help='Stop service').set_defaults(func=stop_service)
    subparsers.add_parser('restart', help='Restart service').set_defaults(func=restart_service)
    subparsers.add_parser('status', help='Check service status').set_defaults(func=status_service)
    subparsers.add_parser('logs', help='Show service logs').set_defaults(func=logs_service)


def _get_service_files(name: str) -> tuple[Path, Path]:
    """Get service file paths for current platform"""
    if SYSTEM == 'Darwin':
        plist_file = Path.home() / f'Library/LaunchAgents/{name}.plist'
        log_file = Path.home() / 'Library/Logs/promnesia.out.log'
        return plist_file, log_file
    elif SYSTEM == 'Linux':
        service_file = Path.home() / f'.config/systemd/user/{name}'
        log_file = Path.home() / '.local/share/promnesia/promnesia.log'
        return service_file, log_file
    else:
        # Fallback to PID-based service
        pid_file = Path.home() / '.promnesia_service.pid'
        log_file = Path.home() / 'Library/Logs/promnesia.log'
        return pid_file, log_file


def start_service(args: argparse.Namespace) -> None:
    """Start the installed service"""
    service_file, log_file = _get_service_files(args.name)
    
    if SYSTEM == 'Darwin' and service_file.exists():
        subprocess.run(['launchctl', 'load', str(service_file)], check=True)
        logger.info("Started LaunchAgent service")
        
    elif SYSTEM == 'Linux' and service_file.exists():
        subprocess.run(['systemctl', '--user', 'start', args.name], check=True)
        logger.info("Started systemd service")
        
    else:
        logger.error("No service file found. Run 'promnesia service install' first")


def stop_service(args: argparse.Namespace) -> None:
    """Stop the installed service"""
    service_file, log_file = _get_service_files(args.name)
    
    if SYSTEM == 'Darwin' and service_file.exists():
        # Check if service is actually running before trying to unload
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if args.name in result.stdout:
            subprocess.run(['launchctl', 'unload', str(service_file)], check=False)
            logger.info("Stopped LaunchAgent service")
        else:
            logger.info("LaunchAgent service not running")
        
    elif SYSTEM == 'Linux' and service_file.exists():
        subprocess.run(['systemctl', '--user', 'stop', args.name], check=False)
        logger.info("Stopped systemd service")
        
    else:
        logger.error("No service file found")


def status_service(args: argparse.Namespace) -> None:
    """Check service status"""
    service_file, log_file = _get_service_files(args.name)
    
    if SYSTEM == 'Darwin' and service_file.exists():
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if args.name in result.stdout:
            logger.info("LaunchAgent service running")
        else:
            logger.info("LaunchAgent service not running")
            
    elif SYSTEM == 'Linux' and service_file.exists():
        result = subprocess.run(['systemctl', '--user', 'is-active', args.name], 
                              capture_output=True, text=True)
        if result.stdout.strip() == 'active':
            logger.info("Systemd service active")
        else:
            logger.info("Systemd service inactive")
            
    else:
        logger.info("No service file found. Run 'promnesia service install' first")


def logs_service(args: argparse.Namespace) -> None:
    """Show service logs"""
    if SYSTEM == 'Darwin':
        log_path = Path.home() / 'Library/Logs/promnesia.out.log'
        if log_path.exists():
            subprocess.run(['tail', '-f', str(log_path)])
        else:
            logger.error("No logs found")
            
    elif SYSTEM == 'Linux':
        subprocess.run(['journalctl', '--user', '-u', args.name, '-f'])
        
    else:
        logger.error("Platform not supported for log viewing")


def restart_service(args: argparse.Namespace) -> None:
    """Restart the service"""
    stop_service(args)
    start_service(args)
