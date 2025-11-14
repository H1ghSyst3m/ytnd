# run.py
"""
Single-script entry point to run all YTND services:
- Syncthing executable
- Telegram Bot
- Manager Server (FastAPI)
"""
import multiprocessing
import subprocess
import signal
import time
import shutil
import os
from pathlib import Path

# Set a custom environment variable to indicate this is the main process
# This helps avoid circular imports or re-initialization issues.
os.environ["YTND_MAIN_RUNNER"] = "1"

from ytnd.bot import main as bot_main
from ytnd.manager_server import run as manager_run
from ytnd.utils import logger

# --- Configuration ---
# Attempt to find the syncthing executable
SYNCTHING_EXECUTABLE = shutil.which("syncthing")
# Log file for syncthing subprocess
SYNCTHING_LOG_FILE = Path(os.getenv("LOG_DIR", "./data/logs")) / "syncthing.log"


def run_bot():
    """Wrapper function to run the bot."""
    logger.info("Starting Telegram bot process...")
    try:
        bot_main()
    except Exception as e:
        logger.error("Telegram bot process failed: %s", e)
        # Force exit to notify the main process
        os._exit(1)


def run_manager():
    """Wrapper function to run the FastAPI manager server."""
    logger.info("Starting manager server process...")
    try:
        manager_run()
    except Exception as e:
        logger.error("Manager server process failed: %s", e)
        os._exit(1)


def main():
    """
    Main function to orchestrate the startup of all services.
    """
    if not SYNCTHING_EXECUTABLE:
        logger.error(
            "FATAL: `syncthing` executable not found in PATH. "
            "Please install Syncthing or ensure its location is in the system's PATH."
        )
        return

    logger.info("Starting all services...")
    processes = []
    syncthing_process = None

    def shutdown_handler(signum, frame):
        """Handle signals for graceful shutdown."""
        logger.warning("Shutdown signal received. Terminating all processes...")
        
        # Terminate multiprocessing processes
        for p in processes:
            if p.is_alive():
                logger.info(f"Terminating process {p.name} (PID: {p.pid})")
                p.terminate()
                p.join(timeout=5)
                if p.is_alive():
                    p.kill() # Force kill if terminate fails
        
        # Terminate syncthing subprocess
        if syncthing_process and syncthing_process.poll() is None:
            logger.info(f"Terminating syncthing process (PID: {syncthing_process.pid})")
            syncthing_process.terminate()
            try:
                syncthing_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                syncthing_process.kill()

        logger.info("All processes terminated. Exiting.")
        exit(0)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # 1. Start Syncthing as a subprocess
        logger.info(f"Starting Syncthing from: {SYNCTHING_EXECUTABLE}")
        SYNCTHING_LOG_FILE.parent.mkdir(exist_ok=True, parents=True)
        with open(SYNCTHING_LOG_FILE, "a", encoding="utf-8") as log_file:
            syncthing_process = subprocess.Popen(
                [SYNCTHING_EXECUTABLE],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
        logger.info(f"Syncthing process started with PID: {syncthing_process.pid}. Logs: {SYNCTHING_LOG_FILE}")
        time.sleep(2) # Give syncthing a moment to start

        # 2. Start Telegram Bot in a separate process
        bot_process = multiprocessing.Process(target=run_bot, name="Bot")
        bot_process.start()
        processes.append(bot_process)
        logger.info(f"Telegram bot process started with PID: {bot_process.pid}")

        # 3. Start Manager Server in another separate process
        manager_process = multiprocessing.Process(target=run_manager, name="Manager")
        manager_process.start()
        processes.append(manager_process)
        logger.info(f"Manager server process started with PID: {manager_process.pid}")

        # Keep the main process alive and monitor child processes
        while True:
            # Check Syncthing process
            if syncthing_process.poll() is not None:
                logger.error(f"Syncthing process terminated unexpectedly with exit code {syncthing_process.returncode}.")
                raise RuntimeError("Syncthing process failed.")

            # Check multiprocessing processes
            for p in processes:
                if not p.is_alive():
                    logger.error(f"Process {p.name} terminated unexpectedly with exit code {p.exitcode}.")
                    raise RuntimeError(f"Process {p.name} failed.")
            
            time.sleep(5)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Main process interrupted. Initiating shutdown...")
    except Exception as e:
        logger.error(f"A critical error occurred in the main runner: {e}")
    finally:
        shutdown_handler(None, None)


if __name__ == "__main__":
    main()