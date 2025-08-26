from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from ..common import logger

SYSTEM = platform.system()


def _get_python_executable() -> str:
    """Get the Python executable used to run Promnesia"""
    # Use the current Python executable
    return sys.executable


def _get_service_files() -> tuple[Path, Path]:
    """Get service file paths for current platform"""
    if SYSTEM == 'Darwin':
        plist_file = Path.home() / 'Library/LaunchAgents/com.promnesia.server.plist'
        log_file = Path.home() / 'Library/Logs/promnesia.log'
        return plist_file, log_file
    elif SYSTEM == 'Linux':
        service_file = Path.home() / '.config/systemd/user/promnesia.service'
        log_file = Path.home() / '.local/share/promnesia/promnesia.log'
        return service_file, log_file
    else:
        # Fallback to PID-based service
        pid_file = Path.home() / '.promnesia_service.pid'
        log_file = Path.home() / 'Library/Logs/promnesia.log'
        return pid_file, log_file


def _create_launchd_service(venv_python: str, work_dir: str) -> str:
    """Create macOS LaunchAgent plist content"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.promnesia.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_python}</string>
        <string>-m</string>
        <string>promnesia</string>
        <string>serve</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{work_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/promnesia.out.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/promnesia.err.log</string>
</dict>
</plist>"""


def _create_systemd_service(venv_python: str) -> str:
    """Create Linux systemd service content"""
    return f"""[Unit]
Description=Promnesia browser extension backend

[Service]
ExecStart={venv_python} -m promnesia serve
Type=simple
Restart=always
RestartSec=5

[Install]
WantedBy=default.target"""


def service_install(args: argparse.Namespace) -> None:
    """Install Promnesia as a system service"""
    python_exe = _get_python_executable()
    work_dir = os.getcwd()
    
    service_file, log_file = _get_service_files()
    
    if SYSTEM == 'Darwin':
        content = _create_launchd_service(python_exe, work_dir)
        service_file.parent.mkdir(parents=True, exist_ok=True)
        service_file.write_text(content)
        logger.info(f"Created LaunchAgent: {service_file}")
        logger.info("To start: launchctl load ~/Library/LaunchAgents/com.promnesia.server.plist")
        
    elif SYSTEM == 'Linux':
        content = _create_systemd_service(python_exe)
        service_file.parent.mkdir(parents=True, exist_ok=True)
        service_file.write_text(content)
        logger.info(f"Created systemd service: {service_file}")
        logger.info("To enable: systemctl --user enable promnesia.service")
        logger.info("To start: systemctl --user start promnesia.service")
        
    else:
        logger.error(f"Platform {SYSTEM} not supported for native service installation")
        logger.info("Use 'promnesia service start' for manual process management")


def service_start(args: argparse.Namespace) -> None:
    """Start Promnesia service"""
    service_file, log_file = _get_service_files()
    
    if SYSTEM == 'Darwin' and service_file.exists():
        subprocess.run(['launchctl', 'load', str(service_file)], check=True)
        logger.info("Started LaunchAgent service")
        
    elif SYSTEM == 'Linux' and service_file.exists():
        subprocess.run(['systemctl', '--user', 'start', 'promnesia.service'], check=True)
        logger.info("Started systemd service")
        
    else:
        # Fallback: start as background process
        if service_file.exists():
            try:
                pid = int(service_file.read_text())
                os.kill(pid, 0)  # Check if process exists
                logger.info(f"Promnesia already running (PID {pid})")
                return
            except (OSError, ValueError):
                service_file.unlink()  # Remove stale PID file
        
        python_exe = _get_python_executable()
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, 'a') as log:
            proc = subprocess.Popen(
                [python_exe, '-m', 'promnesia', 'serve'],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
        
        service_file.write_text(str(proc.pid))
        logger.info(f"Started Promnesia (PID {proc.pid})")
        logger.info(f"Logs: {log_file}")


def service_stop(args: argparse.Namespace) -> None:
    """Stop Promnesia service"""
    service_file, log_file = _get_service_files()
    
    if SYSTEM == 'Darwin' and service_file.exists():
        # Check if service is actually running before trying to unload
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if 'com.promnesia.server' in result.stdout:
            subprocess.run(['launchctl', 'unload', str(service_file)], check=False)
            logger.info("Stopped LaunchAgent service")
        else:
            logger.info("LaunchAgent service not running")
        
    elif SYSTEM == 'Linux' and service_file.exists():
        subprocess.run(['systemctl', '--user', 'stop', 'promnesia.service'], check=False)
        logger.info("Stopped systemd service")
        
    else:
        # Fallback: kill by PID
        if not service_file.exists():
            logger.info("Promnesia not running")
            return
        
        try:
            pid = int(service_file.read_text())
            os.kill(pid, 0)
            os.kill(pid, signal.SIGTERM)
            service_file.unlink()
            logger.info(f"Stopped Promnesia (PID {pid})")
        except OSError:
            logger.info("Promnesia not running (stale PID file)")
            if service_file.exists():
                service_file.unlink()
        except ValueError as e:
            logger.error(f"Error reading PID file: {e}")
            if service_file.exists():
                service_file.unlink()


def service_status(args: argparse.Namespace) -> None:
    """Check Promnesia service status"""
    service_file, log_file = _get_service_files()
    
    if SYSTEM == 'Darwin' and service_file.exists():
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if 'com.promnesia.server' in result.stdout:
            logger.info("LaunchAgent service running")
        else:
            logger.info("LaunchAgent service not running")
            
    elif SYSTEM == 'Linux' and service_file.exists():
        result = subprocess.run(['systemctl', '--user', 'is-active', 'promnesia.service'], 
                              capture_output=True, text=True)
        if result.stdout.strip() == 'active':
            logger.info("Systemd service active")
        else:
            logger.info("Systemd service inactive")
            
    else:
        # Fallback: check PID
        if not service_file.exists():
            logger.info("Promnesia not running")
            return
        
        try:
            pid = int(service_file.read_text())
            os.kill(pid, 0)
            logger.info(f"Promnesia running (PID {pid})")
        except OSError:
            logger.info("Promnesia not running (stale PID file)")
            service_file.unlink()


def service_logs(args: argparse.Namespace) -> None:
    """Show Promnesia service logs"""
    if SYSTEM == 'Darwin':
        log_path = Path.home() / 'Library/Logs/promnesia.out.log'
        if log_path.exists():
            subprocess.run(['tail', '-f', str(log_path)])
        else:
            logger.error("No logs found")
            
    elif SYSTEM == 'Linux':
        subprocess.run(['journalctl', '--user', '-u', 'promnesia.service', '-f'])
        
    else:
        _, log_file = _get_service_files()
        if log_file.exists():
            subprocess.run(['tail', '-f', str(log_file)])
        else:
            logger.error("No log file found")


def service_restart(args: argparse.Namespace) -> None:
    """Restart Promnesia service"""
    service_stop(args)
    service_start(args)


def setup_parser(p: argparse.ArgumentParser) -> None:
    """Setup service management parser"""
    p.set_defaults(func=lambda *_args: p.print_help())
    
    subparsers = p.add_subparsers(dest='service_command', help='Service management commands')
    
    subparsers.add_parser('install', help='Install Promnesia as system service').set_defaults(func=service_install)
    subparsers.add_parser('start', help='Start Promnesia service').set_defaults(func=service_start)
    subparsers.add_parser('stop', help='Stop Promnesia service').set_defaults(func=service_stop)
    subparsers.add_parser('restart', help='Restart Promnesia service').set_defaults(func=service_restart)
    subparsers.add_parser('status', help='Check service status').set_defaults(func=service_status)
    subparsers.add_parser('logs', help='Show service logs').set_defaults(func=service_logs)
